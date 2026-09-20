"""
En tjänst i taget för pipeline-visualiseraren: tåg, kollektivtrafik, väg, flyg, väder och
evenemang, var för sig (färjorna har redan sin egen sida, maritime/relevance.py).

Varje tjänst svarar på samma frågor, i samma ordning:

1. Vad hämtas, varifrån och hur färskt är det (`sources`)?
2. Hur analyseras det, steg för steg (`steps`), och vad blir kvar i varje steg (`funnel`)?
3. Vilka sorter och regler slog till, och hur många gånger (`tiers`, `rules`)?
4. Vad får föraren, och baserat på vad (`cards`, grupperade: notis, bara listan, visas inte)?

Ett kort öppnar hela kedjan för ett tips (`tip_detail`): källhändelserna som de kom,
tolkningen, poängregeln, skälen och notisbeslutet.

Bara med DEBUG, som resten av /api/pipeline: svaren innehåller alla aktiva tips och rå
källdata, utan inloggning.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone

from core import thresholds
from core.ingest import WEATHER_BONUS
from core.models import Opportunity, RailAssessment, ScoringRule, SourceEvent, SourceStatus

CARDS_MAX = 200
NOISE_MAX = 25

TIER_LABEL = {
    "line_paused": "Stopp på linjen",
    "vehicle_cancelled": "Inställd avgång",
    "line_delayed": "Försenad linje",
    "vehicle_delayed": "Försenat fordon",
    "disruption_unclassified": "Störning, oklassad",
    "road_accident_or_closure": "Olycka eller avstängning",
    "road_work": "Vägarbete",
    "road_work_or_queue": "Vägarbete eller kö",
    "arrival_wave": "Ankomstvåg",
    "last_arrival": "Sista ankomsten",
    "ignore": "Brus",
}
MODE_LABEL = {
    "train": "tåg", "bus": "buss", "metro": "tunnelbana", "tram": "spårvagn", "boat": "båt",
    "road": "väg", "flight": "flyg", "unknown": "okänt färdsätt",
}
SOURCE_LABEL = {
    "trafikverket_rail": "Trafikverket järnväg", "trafikverket": "Trafikverket väg", "sl": "SL",
    "vt": "Västtrafik", "trafiklab": "Trafiklab GTFS-RT", "smhi": "SMHI", "swedavia": "Swedavia",
    "aisstream": "AISStream", "ticketmaster": "Ticketmaster", "predicthq": "PredictHQ",
    "thesportsdb": "TheSportsDB (fotboll, ishockey, handboll)",
}

TRAIN = Q(external_id__startswith="tvr:") | Q(kind="transit", mode="train")


def _is_weather(o: Opportunity) -> bool:
    return any(str(r).startswith("väder") for r in (o.reasons or []))


# Tjänsterna. `match` väljer tipsen, `steps` beskriver analysen med källfilen där den bor.
SERVICES: dict[str, dict] = {
    "tag": {
        "title": "Tåg",
        "question": "Var står folk på en perrong för att tåget är inställt eller mycket sent, och kommer de vidare utan taxi?",
        "deliver": "Ett tips per station: vilka tåg som är inställda eller sena, när nästa tåg går, om det var sista "
                   "avgången, rätt till taxiersättning, och en notis när det är allvarligt och inget alternativ finns.",
        "sources": ["trafikverket_rail", "sl", "vt", "trafiklab"],
        "match": TRAIN,
        "steps": [
            ("Hämtning", "Trafikverkets TrainAnnouncement var 90:e sekund, hela landet i två sidade frågor: inställda "
             "och kraftigt försenade avgångar de senaste timmarna. Pendeltåg och regionaltåg (Pågatåg, pendeltåg i "
             "Stockholm och Göteborg) kommer från SL, Västtrafik och Trafiklab.", "core/sources/trafikverket_rail.py"),
            ("Tolkning", "Avgångarna grupperas per station. Källans text och tågtyp avgör sorten: inställd avgång, "
             "stopp på linjen eller försenad linje.", "core/scoring.py"),
            ("Nästa avgång", "För varje station frågar ResRobot efter nästa avgång mot samma mål, aldrig samma inställda "
             "tåg. Lång väntan eller sista avgången väger tyngre. Ersättningstrafik som källan skriver ut räknas som "
             "alternativ.", "core/sources/resrobot.py, core/alternatives.py"),
            ("Poäng", "Grundpoäng per sort och regel (tabellen Regler nedan). Rätt till taxiersättning (lag 2015:953, "
             "per län) och hårt väder från SMHI kan höja.", "core/scoring.py, core/compensation.py"),
            ("Notis", f"Notis bara när sorten är notisvärd, poängen minst {thresholds.NOTIFY_SCORE_FLOOR} och inget "
             "alternativ finns, och bara till förare vars körområde tipset ligger i.", "core/notify.py decide()"),
        ],
    },
    "kollektivtrafik": {
        "title": "Buss, tunnelbana och spårvagn",
        "question": "Var blir resenärer stående för att bussen, tunnelbanan eller spårvagnen är inställd eller står still?",
        "deliver": "Ett tips per störning med plats, sort och skäl. Brus (hiss ur funktion, stängd toalett) tas "
                   "bort; en inställd linje utan ersättning kan ge notis.",
        "sources": ["sl", "vt", "trafiklab"],
        "match": Q(kind="transit") & ~TRAIN,
        "steps": [
            ("Hämtning", "SL:s störningar (öppet, var 90:e sekund), Västtrafiks trafiksituationer (OAuth) och "
             "Trafiklabs GTFS-RT ServiceAlerts för de regionala trafikhuvudmännen.",
             "core/sources/sl.py, core/sources/vasttrafik.py, core/sources/trafiklab.py"),
            ("Färdsätt", "Buss, tunnelbana, spårvagn eller båt, ur källans eget fält eller ur texten.", "core/mode.py"),
            ("Tolkning", "Allvaret läses ur ordvalet: inställd, stopp, försenad. Hiss, toalett och cykelplatser blir "
             "brus och visas aldrig för föraren.", "core/text_scoring.py, core/taxi_relevance.py"),
            ("Poäng", "Grundpoäng per sort och färdsätt (tabellen Regler nedan); väder från SMHI kan höja.",
             "core/text_scoring.py"),
            ("Notis", f"Notis bara när sorten är notisvärd, poängen minst {thresholds.NOTIFY_SCORE_FLOOR} och inget "
             "alternativ finns, och bara till förare vars körområde tipset ligger i.", "core/notify.py decide()"),
        ],
    },
    "vag": {
        "title": "Väg",
        "question": "Är vägen dit avstängd, eller har det hänt en olycka på vägen?",
        "deliver": "Sammanhang för en förare som redan kör: olyckor, avstängningar, köer och vägarbeten, med låg "
                   "poäng. En väghändelse är inget skäl att köra någonstans.",
        "sources": ["trafikverket"],
        "match": Q(kind="road"),
        "steps": [
            ("Hämtning", "Trafikverkets Situation var 90:e sekund, alla län, sidindelat tills hela svaret är hämtat.",
             "core/sources/trafikverket_road.py"),
            ("Tolkning", "Sorten ur händelsetypen: olycka eller avstängning, vägarbete, vägarbete eller kö.",
             "core/sources/trafikverket_road.py"),
            ("Poäng", f"Grundpoängen kapas lågt (högst 15): en olycka försenar dem som redan sitter i bil, ingen "
             f"lämnar bilen i en kö och tar taxi. Hårt väder lägger till {WEATHER_BONUS}, så högst {15 + WEATHER_BONUS}.",
             "core/taxi_relevance.py, core/ingest.py"),
            ("Notis", f"Olycka eller avstängning är en notisvärd sort, men även med väder ({15 + WEATHER_BONUS}) ligger "
             f"poängen under {thresholds.NOTIFY_SCORE_FLOOR}: det blir aldrig en notis, bara en rad i listan.",
             "core/thresholds.py"),
        ],
    },
    "flyg": {
        "title": "Flyg",
        "question": "När landar många plan samtidigt sent på kvällen, eller det sista planet för dagen?",
        "deliver": "Ankomstvågor (många landningar samma halvtimme) och sista ankomsten på de små flygplatserna, "
                   "i listan. Ankomstvågor ger med avsikt ingen notis.",
        "sources": ["swedavia"],
        "match": Q(kind="flight"),
        "steps": [
            ("Hämtning", "Swedavia FlightInfo v2 var femte minut, per flygplats och lokalt datum. Lokalt kan hämtningen "
             "vara avstängd (poll-flights i TAXITIPS_BEAT_DISABLE) för att spara kvoten.", "core/sources/swedavia.py"),
            ("Tolkning", "Ankomsterna räknas per 30-minutersfönster. Status DEL betyder borttagen, inte försenad; "
             "förseningen räknas ur tiderna.", "core/sources/swedavia.py"),
            ("Regler", "Stora flygplatser: ankomstvåg när minst N plan landar samma halvtimme sent på kvällen (N per "
             "flygplats nedan). Små: sista ankomsten, när inget mer plan landar inom två timmar.",
             "core/flight_scoring.py, core/thresholds.py AIRPORTS"),
            ("Notis", "Ankomstvåg och sista ankomst syns i listan men ger ingen notis: de är förutsägbara och inte "
             "akuta.", "core/thresholds.py NOTIFY_WORTHY_TIERS"),
        ],
    },
    "vader": {
        "title": "Väder",
        "question": "Gör vädret en redan relevant störning värre, så att fler tar taxi?",
        "deliver": "Inget eget tips: vädret står som ett skäl på tips som redan finns (\"väder: hård vind\") och höjer "
                   "deras poäng.",
        "sources": ["smhi"],
        "match": None,  # tipsen med ett väderskäl, se _is_weather
        "steps": [
            ("Hämtning", "SMHI:s punktprognos för varje marknads ankarort och städer, inuti de andra pollarna, cachad "
             "30 minuter.", "core/sources/smhi.py"),
            ("Trösklar", "Nederbörd minst 1 mm/h med minst 40 % sannolikhet, vind minst 12 m/s, åska minst 30 %, "
             "minusgrader med minst 40 % fruset.", "core/sources/smhi.py"),
            ("Påverkan", f"Vädret skapar aldrig ett tips själv. Det höjer en störning som redan är relevant med "
             f"{WEATHER_BONUS} poäng (högst 100), efter klassificeringen, och skrivs ut som skäl.", "core/ingest.py"),
        ],
    },
}


def _notify(o: Opportunity) -> tuple[str, str]:
    """(grupp, förklaring): notis och lista, bara listan, eller visas inte."""
    tier_label = TIER_LABEL.get(o.severity_tier, o.severity_tier)
    if o.severity_tier == "ignore":
        return "hidden", "Brus: ingen taxisignal, visas inte för föraren"
    if (o.demand_score or 0) <= 0:
        return "hidden", "Poäng 0: visas inte för föraren"
    if thresholds.is_notify_worthy(o.severity_tier, o.demand_score, o.has_alternative):
        return "notify", (f"Notis: {tier_label.lower()} är notisvärd, poäng {o.demand_score} ≥ "
                          f"{thresholds.NOTIFY_SCORE_FLOOR} och inget alternativ. Går till förare i körområdet.")
    if o.severity_tier not in thresholds.NOTIFY_WORTHY_TIERS:
        return "list", f"Bara i listan: sorten {tier_label.lower()} ger aldrig notis"
    if o.has_alternative:
        return "list", "Bara i listan: källan skriver ut ett alternativ, så ingen väcks för det"
    return "list", f"Bara i listan: poäng {o.demand_score} är under notisgränsen {thresholds.NOTIFY_SCORE_FLOOR}"


GROUPS = {
    "notify": "Notis och lista",
    "list": "Bara i listan",
    "hidden": "Visas inte",
}


def _rule_info(rule_id: str, rules: list[ScoringRule]) -> dict | None:
    """Poängregeln bakom `rule_id` (färdsätt.sort.villkor), om den finns i ScoringRule."""
    parts = (rule_id or "").split(".")
    if len(parts) < 2:
        return None
    mode, tier, condition = parts[0], parts[1], (parts[2] if len(parts) > 2 else "")
    for rule in rules:
        if rule.tier == tier and (rule.condition or "") == condition and (rule.mode or "") in ("", mode):
            return {"floor": rule.floor, "cap": rule.cap, "confidence": rule.confidence, "note": rule.note}
    return None


def _card(o: Opportunity, now) -> dict:
    group, why = _notify(o)
    badges = [{"text": TIER_LABEL.get(o.severity_tier, o.severity_tier), "tone": group}]
    if o.mode and o.mode not in ("road",):
        badges.append({"text": MODE_LABEL.get(o.mode, o.mode), "tone": "none"})
    badges.append({"text": f"poäng {o.demand_score}", "tone": "score"})
    if o.compensation_eligible:
        badges.append({"text": f"ersättning {o.compensation_amount_kr or ''} kr".replace("  ", " "), "tone": "none"})
    if o.is_last_departure:
        badges.append({"text": "sista avgången", "tone": "warn"})
    elif o.next_departure_minutes is not None:
        badges.append({"text": f"nästa avgång om {o.next_departure_minutes} min", "tone": "none"})
    if o.has_alternative:
        badges.append({"text": "alternativ finns", "tone": "none"})
    return {
        "id": str(o.id),
        "title": o.title,
        "sub": ", ".join(o.places or []) or (o.region or ""),
        "group": group,
        "groupLabel": GROUPS[group],
        "score": o.demand_score,
        "tier": o.severity_tier,
        "rule": o.rule_id,
        "badges": badges,
        "why": [why, *[str(r) for r in (o.reasons or [])]],
        "lat": o.lat,
        "lon": o.lon,
        "at": o.start_time.isoformat() if o.start_time else None,
        "until": o.end_time.isoformat() if o.end_time else None,
    }


def _source_rows(keys: list[str], now) -> list[dict]:
    from core.pipeline_view import _source_health

    known = {row["key"]: row for row in _source_health(now)}
    out = []
    for key in keys:
        if key in known:
            out.append(known[key])
            continue
        st = SourceStatus.objects.filter(source=key).first()
        out.append({
            "key": key, "label": SOURCE_LABEL.get(key, key), "what": "",
            "state": ("ok" if st.ok else "fel") if st else "saknas",
            "message": (st.message or "") if st else "", "events": st.events if st else 0,
            "written": st.written if st else 0, "checkedAt": st.checked_at.isoformat() if st else None,
            "ageMinutes": int((now - st.checked_at).total_seconds() // 60) if st else None,
            # Källor utan egen gräns (PredictHQ hämtas live vid behov): senaste körningen, om den lyckades.
            "lastSuccessAgeMinutes": (int((now - (st.last_success_at or st.checked_at)).total_seconds() // 60)
                                      if st and (st.last_success_at or st.ok) else None),
            "maxAgeMinutes": None, "detail": (st.detail or {}) if st else {},
        })
    return out


def build(key: str, now=None, q: str = "") -> dict:
    now = now or timezone.now()
    if key == "evenemang":
        return _events(now)
    svc = SERVICES[key]
    active = Opportunity.objects.filter(end_time__gt=now)
    rows = list(active.filter(svc["match"])) if svc["match"] is not None else [o for o in active if _is_weather(o)]
    rules = list(ScoringRule.objects.all())

    grouped = Counter(_notify(o)[0] for o in rows)
    funnel = [
        {"label": "Aktiva tips från källorna", "n": len(rows),
         "note": "Allt som bedömts och inte gått ut, före alla filter."},
        {"label": "Inte brus", "n": sum(1 for o in rows if o.severity_tier != "ignore"),
         "note": "Brus (hiss, toalett, cykelplatser) visas aldrig för föraren."},
        {"label": "I förarens lista", "n": grouped["notify"] + grouped["list"],
         "note": "Poäng över 0. Föraren ser dem som ligger i hens körområde."},
        {"label": "Ger notis", "n": grouped["notify"],
         "note": f"Notisvärd sort, poäng minst {thresholds.NOTIFY_SCORE_FLOOR}, inget alternativ."},
    ]

    tier_counts = Counter(o.severity_tier for o in rows)
    tiers = [{
        "tier": tier, "label": TIER_LABEL.get(tier, tier), "n": n,
        "level": ("hög" if tier in thresholds.HIGH_SEVERITY_TIERS
                  else "medel" if tier in thresholds.MEDIUM_SEVERITY_TIERS else "låg"),
        "notifyWorthy": tier in thresholds.NOTIFY_WORTHY_TIERS,
    } for tier, n in tier_counts.most_common()]

    by_rule: dict[str, list[Opportunity]] = {}
    for o in rows:
        by_rule.setdefault(o.rule_id or "—", []).append(o)
    rule_rows = []
    for rule_id, members in sorted(by_rule.items(), key=lambda kv: -len(kv[1])):
        scores = [m.demand_score for m in members]
        best = max(members, key=lambda m: m.demand_score)
        rule_rows.append({
            "rule": rule_id, "n": len(members), "avgScore": round(sum(scores) / len(scores)),
            "maxScore": max(scores), "example": best.title, "exampleId": str(best.id),
            "scoring": _rule_info(rule_id, rules),
        })

    # Sökningen gäller korten, inte tratten: tratten visar alltid hela tjänsten.
    needle = (q or "").strip().lower()
    searched = [o for o in rows if not needle or needle in f"{o.title} {' '.join(o.places or [])} {o.region or ''}".lower()]
    shown = sorted((o for o in searched if _notify(o)[0] != "hidden"),
                   key=lambda o: ({"notify": 0, "list": 1}[_notify(o)[0]], -o.demand_score))
    noise = [o for o in searched if _notify(o)[0] == "hidden"][:NOISE_MAX]
    steps = [{"title": title, "text": text, "code": code} for title, text, code in svc["steps"]]
    return {
        "key": key,
        "title": svc["title"],
        "question": svc["question"],
        "deliver": svc["deliver"],
        "generatedAt": now.isoformat(),
        "sources": _source_rows(svc["sources"], now),
        "steps": steps,
        "funnel": funnel,
        "tiers": tiers,
        "rules": rule_rows,
        "cards": [_card(o, now) for o in shown[:CARDS_MAX]] + [_card(o, now) for o in noise],
        "query": needle,
        "counts": {"active": len(rows), "shown": len(shown), "listed": min(len(shown), CARDS_MAX),
                   "noiseShown": len(noise), "hidden": grouped["hidden"]},
        "groups": GROUPS,
        "extra": _extra(key, rows),
    }


def _extra(key: str, rows: list[Opportunity]) -> dict:
    if key == "tag":
        from core.pipeline_view import _next_departure, _rail_launch

        return {"rail": _rail_launch(), "nextDeparture": _next_departure(rows)}
    if key == "flyg":
        return {"airports": [
            {"iata": iata, "name": a["name"], "city": a.get("city", ""), "rule": a["rule"], "waveMin": a.get("wave_min")}
            for iata, a in thresholds.AIRPORTS.items()
        ], "history": _flight_history(timezone.now())}
    if key == "vag":
        return {"maxScore": max((o.demand_score for o in rows), default=0)}
    return {}


HISTORY_DAYS = 14


def _flight_history(now) -> dict:
    """
    Swedavia bakåt i tiden: flygtipsen per dag och flygplats, och vad senaste hämtningen gav
    per flygplats. Tipsen ligger kvar tills gallringen tar dem (7 dygn i drift), så en dag utan
    rader betyder att ingen hämtning gick den dagen, eller att inget fönster nådde tröskeln.
    """
    today = timezone.localtime(now).date()
    first = today - timedelta(days=HISTORY_DAYS - 1)
    days = {(first + timedelta(days=i)).isoformat(): {"wave": 0, "last": 0, "airports": Counter(), "maxScore": 0}
            for i in range(HISTORY_DAYS + 1)}
    for external_id, rule, start, score in Opportunity.objects.filter(
        kind="flight", start_time__date__gte=first,
    ).values_list("external_id", "rule_id", "start_time", "demand_score"):
        day = days.get(timezone.localtime(start).date().isoformat())
        if day is None:
            continue
        day["wave" if (rule or "").endswith("arrival_wave") else "last"] += 1
        day["airports"][(external_id.split(":") + ["?", "?"])[1]] += 1
        day["maxScore"] = max(day["maxScore"], score or 0)
    status = SourceStatus.objects.filter(source="swedavia").first()
    detail = (status.detail or {}) if status else {}
    fetched = detail.get("last_fetch") or {}
    runs = [
        {"iata": iata, "name": thresholds.AIRPORTS.get(iata, {}).get("name", iata),
         "arrivals": a.get("arrivals"), "notArriving": a.get("not_arriving"), "windows": a.get("windows"),
         "fetchedAt": fetched.get(f"{iata}:today")}
        for iata, a in (detail.get("airports") or {}).items()
    ]
    return {
        "days": [{"date": d, **{k: v for k, v in row.items() if k != "airports"}, "airports": dict(row["airports"])}
                 for d, row in sorted(days.items(), reverse=True)],
        "runs": runs,
        "calls": detail.get("calls"), "budget": detail.get("budget"), "month": detail.get("month"),
        "lastSuccessAt": status.last_success_at.isoformat() if status and status.last_success_at else None,
    }


# PredictHQ: PHQ Rank anger hur illa förseningen är (docs, "Airport Delays"). Titeln säger
# "Moderate Delays" även vid rank 20, så nivån läses ur ranken, inte ur titeln.
DELAY_LEVELS = {20: "Minimal", 40: "Måttlig", 70: "Betydande", 90: "Svår"}
DELAY_CACHE_SECONDS = 600
PRIORITY_AIRPORTS = ("CPH",)


def _delay_level(rank) -> tuple[int, str]:
    rank = int(rank or 0)
    level = max((r for r in DELAY_LEVELS if r <= rank), default=20)
    return level, DELAY_LEVELS[level]


def airport_delays_live(back_days: int, ahead_days: int) -> dict:
    """
    PredictHQ:s flygförseningar i Sverige och på Köpenhamn (CPH), `back_days` bakåt och `ahead_days`
    framåt. Live och sparas inte i databasen: villkoren förbjuder lagring utan skriftligt avtal.
    Svaret hålls i processens cache i tio minuter, så att en omladdning inte kostar nya anrop.
    """
    from django.core.cache import cache

    key = f"pipeline:airport-delays:{back_days}:{ahead_days}"
    cached = cache.get(key)
    if cached is not None:
        return {**cached, "cached": True}
    data = _fetch_airport_delays(back_days, ahead_days)
    if "error" not in data:
        cache.set(key, data, DELAY_CACHE_SECONDS)
    return {**data, "cached": False}


def _fetch_airport_delays(back_days: int, ahead_days: int) -> dict:
    import datetime as dt

    from events.sources import predicthq
    from events.timing import STOCKHOLM

    token = getattr(settings, "PREDICTHQ_ACCESS_TOKEN", "")
    if not token:
        return {"error": "PREDICTHQ_ACCESS_TOKEN saknas i taxitips-backend/.env."}
    client = predicthq.Client(token)
    now = timezone.now()
    today = timezone.localtime(now).date()
    first, last = today - dt.timedelta(days=back_days), today + dt.timedelta(days=ahead_days)

    def parse(value):
        try:
            return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
        except ValueError:
            return None

    delays = []
    for country in ("SE", "DK"):
        url, query = predicthq.API_URL, {
            "country": country, "category": "airport-delays", "active.gte": first.isoformat(),
            "active.lte": last.isoformat(), "active.tz": "Europe/Stockholm", "sort": "-start", "limit": 200,
        }
        while url:
            payload = client.get(url, query)
            query = None
            for event in payload.get("results") or []:
                if country == "DK" and not predicthq.is_copenhagen_airport(event):
                    continue
                title = event.get("title") or ""
                _kind, _, airport = title.partition(" - ")
                code = airport.rsplit("(", 1)[-1].rstrip(")") if "(" in airport else ""
                venue = next((e for e in event.get("entities") or [] if e.get("type") == "venue"), {})
                point = ((event.get("geo") or {}).get("geometry") or {}).get("coordinates") or [None, None]
                start, end = parse(event.get("start")), parse(event.get("end"))
                seen = parse(event.get("first_seen"))
                level, label = _delay_level(event.get("rank"))
                local_start = start.astimezone(STOCKHOLM) if start else None
                delays.append({
                    "id": event.get("id"), "code": code, "country": country,
                    "airport": venue.get("name") or airport.rsplit(" (", 1)[0] or title,
                    "rank": event.get("rank"), "localRank": event.get("local_rank"), "level": level, "levelLabel": label,
                    "start": event.get("start"), "end": event.get("end"),
                    "startLocal": event.get("start_local"), "endLocal": event.get("end_local"),
                    "timezone": event.get("timezone"),
                    "minutes": round((event.get("duration") or 0) / 60),
                    "ongoing": bool(start and end and start <= now < end),
                    "hour": local_start.hour if local_start else None,
                    "date": local_start.date().isoformat() if local_start else None,
                    # Hur fort PredictHQ såg förseningen: negativ = innan den började.
                    "seenAfterMin": round((seen - start).total_seconds() / 60) if seen and start else None,
                    "firstSeen": event.get("first_seen"), "updated": event.get("updated"),
                    "lat": point[1] if len(point) > 1 else None, "lon": point[0] if point else None,
                })
            url = payload.get("next")
    delays.sort(key=lambda d: d["start"] or "", reverse=True)

    airports: dict[str, dict] = {}
    for d in delays:
        row = airports.setdefault(d["code"] or d["airport"], {
            "code": d["code"], "airport": d["airport"], "country": d["country"], "lat": d["lat"], "lon": d["lon"],
            "n": 0, "ongoing": 0, "levels": {str(level): 0 for level in DELAY_LEVELS}, "hours": [0] * 24,
            "days": {}, "minutes": 0, "latest": d, "seenAfter": [],
        })
        row["n"] += 1
        row["ongoing"] += d["ongoing"]
        row["levels"][str(d["level"])] += 1
        row["minutes"] += d["minutes"]
        if d["hour"] is not None:
            # Varje timme förseningen pågår, inte bara starttimmen: 01-04 räknas som 01, 02 och 03.
            for step in range(max(1, (d["minutes"] + 59) // 60)):
                row["hours"][(d["hour"] + step) % 24] += 1
        if d["date"]:
            row["days"][d["date"]] = row["days"].get(d["date"], 0) + 1
        if d["seenAfterMin"] is not None:
            row["seenAfter"].append(d["seenAfterMin"])
    summary = []
    for row in airports.values():
        seen = sorted(row.pop("seenAfter"))
        row["seenAfterMedianMin"] = seen[len(seen) // 2] if seen else None
        row["avgMinutes"] = round(row["minutes"] / row["n"]) if row["n"] else 0
        summary.append(row)
    summary.sort(key=lambda r: (r["code"] not in PRIORITY_AIRPORTS, -r["n"]))
    return {
        "from": first.isoformat(), "to": last.isoformat(), "fetchedAt": now.isoformat(),
        "calls": client.call_count, "stored": False, "levels": {str(k): v for k, v in DELAY_LEVELS.items()},
        "airports": summary, "delays": delays,
        "attribution": "Flygförseningar: PredictHQ (live, sparas inte)",
    }


def _events(now) -> dict:
    """Evenemangen i samma form, byggda på events/explain.py."""
    from events import timing
    from events.explain import build as explain

    ev = explain(now)
    rules, totals = ev.get("rules") or {}, ev.get("totals") or {}
    durations = ", ".join(f"{d['label'].lower()} {d['minutes']} min" for d in rules.get("durations", []))
    rights = {r["source"]: r for r in ev.get("rights") or []}
    tm = rights.get("ticketmaster") or {}
    end_label = {"source": "sluttid från källan", "predicted": "sluttid förutsagd av källan",
                 "estimated": "sluttid uppskattad", "unknown": "sluttid okänd"}
    cards = []
    for e in ev.get("calendar") or []:
        # Sorten föraren filtrerar på: sporten för sportevenemang, annars kategorin.
        kind = e.get("sport") or e.get("category") or "ovrigt"
        kind_label = e.get("sportLabel") or e.get("categoryLabel") or kind
        badges = [{"text": kind_label, "tone": "none"},
                  {"text": end_label.get(e.get("endBasis"), e.get("endBasis") or ""),
                   "tone": "warn" if e.get("endBasis") in ("estimated", "unknown") else "none"}]
        if e.get("venueCapacity"):
            badges.append({"text": f"arena för {e['venueCapacity']:,}".replace(",", " "), "tone": "none"})
        elif e.get("sizeLabel") and e.get("sizeLevel") != "okand":
            badges.append({"text": e["sizeLabel"], "tone": "none"})
        why = [
            f"Slutar {e.get('endLocal') or '?'}" + (f" ({end_label.get(e.get('endBasis'), '')})" if e.get("endBasis") else ""),
            f"Utsläpp: folk går ut från {e.get('endLocal') or '?'} till {e.get('leaveUntilLocal') or '?'}",
        ]
        if e.get("endNote"):
            why.append(e["endNote"])
        cards.append({
            "id": e["id"], "title": e.get("name") or "", "group": e.get("startDate") or "",
            "kind": kind, "kindLabel": kind_label,
            "groupLabel": e.get("startDate") or "",
            "sub": " · ".join(x for x in (e.get("venueName"), e.get("city")) if x),
            "badges": [b for b in badges if b["text"]],
            "why": why, "lat": e.get("lat"), "lon": e.get("lon"),
            "at": e.get("startAt"), "until": e.get("endAt"),
            "timeText": f"{e.get('startLocal') or '?'}–{e.get('endLocal') or '?'}",
            "detail": {k: e.get(k) for k in ("sourceLabel", "url", "address", "statusLabel", "attendanceText",
                                             "rank", "localRank", "multiDay", "timeKnown")},
        })
    return {
        "key": "evenemang",
        "title": "Evenemang",
        "question": "När och var slutar ett evenemang, så att många vill hem samtidigt?",
        "deliver": "En kalender per datum med plats, start och sluttid, och när folk går ut. I förarappen bara för "
                   "källor med avtal för visning; lokalt visas en förhandsvisning.",
        "generatedAt": now.isoformat(),
        "sources": _source_rows(["ticketmaster", "thesportsdb", "predicthq"], now),
        "steps": [
            {"title": "Hämtning", "code": "events/sources/, events/ingest.py",
             "text": f"Ticketmaster var {rules.get('cadenceHours', 6)}:e timme, hela Sverige, "
                     f"{rules.get('horizonDays', 120)} dagar framåt. PredictHQ hämtas bara live här och sparas inte "
                     "utan skriftligt avtal."},
            {"title": "Rensning", "code": "events/timing.py, events/matching.py",
             "text": f"Tillägg som inte är evenemang (parkering, VIP-paket, kuponger) tas bort. Samma evenemang från två "
                     f"källor slås ihop: inom {rules.get('duplicateMaxMeters', 400)} m, start inom "
                     f"{rules.get('duplicateMaxStartGapMin', 90)} min och liknande namn."},
            {"title": "Sluttid", "code": "events/timing.py",
             "text": f"Från källan när den finns, annars uppskattad efter kategori: {durations}."},
            {"title": "Utsläpp", "code": "events/timing.py",
             "text": f"Folk går ut från sluttiden och {rules.get('leaveWindowMin', 45)} minuter framåt: då vill många "
                     "hem samtidigt."},
            {"title": "Rättigheter", "code": "events/rights.py",
             "text": f"Ticketmaster: lagring {'tillåten' if tm.get('mayStore') else 'avstängd'}, visning i appen "
                     f"{'tillåten' if tm.get('mayShowInApp') else 'avstängd (' + (tm.get('appRefusal') or 'ingen referens') + ')'}."},
        ],
        "funnel": [
            {"label": "Sparade evenemang", "n": totals.get("stored", 0), "note": "Allt som hämtats och inte gallrats."},
            {"label": "Kommande", "n": totals.get("upcomingAll", 0), "note": "Inte redan slut."},
            {"label": "Inom 30 dagar", "n": totals.get("upcoming30", 0), "note": "Det appen visar som standard."},
        ],
        "tiers": [{"tier": c["category"], "label": c["label"], "n": c["n"], "level": "", "notifyWorthy": False}
                  for c in ev.get("byCategory") or []],
        "rules": [],
        "cards": cards,
        "predicthqLive": ev.get("predicthqLive"),
        "counts": {"active": len(cards), "shown": len(cards), "listed": len(cards), "noiseShown": 0,
                   "hidden": totals.get("hidden", 0)},
        "groups": {},
        "extra": {"byCity": ev.get("byCity") or [], "endBasis": ev.get("endBasis") or {}},
        # Namnen på sorterna i den ordning filtret visar dem, även för PredictHQ live som slås in på sidan.
        "kindLabels": {**{k: v for k, v in timing.SPORT_LABELS.items()},
                       **{k: v for k, v in timing.CATEGORY_LABELS.items() if k != "sport"}},
    }


def tip_detail(opportunity_id: str) -> dict | None:
    """Hela kedjan för ett tips: källhändelserna som de kom, tolkningen, regeln och notisbeslutet."""
    o = Opportunity.objects.filter(id=opportunity_id).first()
    if o is None:
        return None
    now = timezone.now()
    ids = [str(i) for i in (o.source_event_ids or [])]
    events = {str(se.id): se for se in SourceEvent.objects.filter(id__in=ids)}
    group, why = _notify(o)
    assessment = RailAssessment.objects.filter(opportunity=o).order_by("-created_at").first()
    card = _card(o, now)
    return {
        **card,
        "summary": o.summary,
        "mode": o.mode,
        "modeLabel": MODE_LABEL.get(o.mode, o.mode),
        "tierLabel": TIER_LABEL.get(o.severity_tier, o.severity_tier),
        "level": o.level,
        "confidence": o.confidence,
        "reasons": o.reasons or [],
        "notify": {"group": group, "why": why,
                   "worthyTier": o.severity_tier in thresholds.NOTIFY_WORTHY_TIERS,
                   "floor": thresholds.NOTIFY_SCORE_FLOOR, "hasAlternative": o.has_alternative},
        "scoring": _rule_info(o.rule_id, list(ScoringRule.objects.all())),
        "nextDeparture": {"minutes": o.next_departure_minutes,
                          "at": o.next_departure_at.isoformat() if o.next_departure_at else None,
                          "isLast": o.is_last_departure},
        "alternative": {"has": o.has_alternative, "note": o.alternative_note},
        "compensation": {"eligible": o.compensation_eligible, "amountKr": o.compensation_amount_kr},
        "area": {"region": o.region, "county": o.county_code, "municipality": o.municipality_code},
        "times": {"start": card["at"], "end": card["until"],
                  "computedAt": o.computed_at.isoformat() if o.computed_at else None,
                  "notifiedAt": o.notified_at.isoformat() if o.notified_at else None},
        "aiReview": {"ruleScore": assessment.rule_score, "modelScore": assessment.model_score,
                     "finalScore": assessment.final_score, "verdict": assessment.verdict} if assessment else None,
        "sourceEvents": [
            {"source": se.source, "sourceLabel": SOURCE_LABEL.get(se.source, se.source), "externalId": se.external_id,
             "fetchedAt": se.fetched_at.isoformat() if se.fetched_at else None,
             "activeFrom": se.active_from.isoformat() if se.active_from else None,
             "activeTo": se.active_to.isoformat() if se.active_to else None,
             "lat": se.lat, "lon": se.lon, "raw": se.raw}
            for se in (events.get(i) for i in ids) if se is not None
        ],
        "missingSourceEvents": sum(1 for i in ids if i not in events),
    }


def overview(now=None) -> dict:
    """En rad per tjänst för startsidan: hur färsk, hur mycket, och vad föraren får."""
    now = now or timezone.now()
    active = Opportunity.objects.filter(end_time__gt=now)
    out = []
    for key, svc in SERVICES.items():
        rows = list(active.filter(svc["match"])) if svc["match"] is not None else [o for o in active if _is_weather(o)]
        groups = Counter(_notify(o)[0] for o in rows)
        out.append({"key": key, "title": svc["title"], "deliver": svc["deliver"], "question": svc["question"],
                    "sources": _source_rows(svc["sources"][:1], now),
                    "counts": {"active": len(rows), "notify": groups["notify"], "list": groups["list"],
                               "hidden": groups["hidden"]}})
    ev = _events(now)
    out.append({"key": "evenemang", "title": ev["title"], "deliver": ev["deliver"], "question": ev["question"],
                "sources": ev["sources"][:1],
                "counts": {"active": ev["counts"]["active"], "upcoming30": ev["funnel"][2]["n"]}})
    return {"generatedAt": now.isoformat(), "services": out}


def _debug_only(view):
    def wrapped(request, *args, **kwargs):
        if not settings.DEBUG:
            return JsonResponse({"error": "not_found"}, status=404)
        return view(request, *args, **kwargs)
    return wrapped


@_debug_only
def service(request, key: str):
    """GET /api/pipeline/service/<key>"""
    if key not in SERVICES and key != "evenemang":
        return JsonResponse({"error": f"okänd tjänst: {key}"}, status=404)
    return JsonResponse(build(key, q=request.GET.get("q", "")), json_dumps_params={"ensure_ascii": False})


@_debug_only
def tip(request, opportunity_id):
    """GET /api/pipeline/tip/<uuid>"""
    data = tip_detail(str(opportunity_id))
    if data is None:
        return JsonResponse({"error": "tipset finns inte (utgånget och gallrat?)"}, status=404)
    return JsonResponse(data, json_dumps_params={"ensure_ascii": False})


@_debug_only
def airport_delays(request):
    """GET /api/pipeline/airport-delays?back=90&ahead=14"""
    def days(name, default):
        try:
            return max(0, min(90, int(request.GET.get(name, default))))
        except ValueError:
            return default
    return JsonResponse(airport_delays_live(days("back", 90), days("ahead", 14)), json_dumps_params={"ensure_ascii": False})


@_debug_only
def services(request):
    """GET /api/pipeline/services"""
    return JsonResponse(overview(), json_dumps_params={"ensure_ascii": False})
