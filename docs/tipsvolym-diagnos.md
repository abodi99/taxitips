# Tipsvolymen: varför förarna ser färre tips (2026-10-08)

Mätt mot produktion 2026-10-08, **enbart läsande** (`SELECT`). Varje siffra har
sin fråga längst ner. Fönstret är 10-01 → 10-08: gallringen tar tips sju dygn
efter `end_time`, så äldre dagar finns inte kvar. Dag = `computed_at` (första
skrivningen, behålls av upserten) i svensk tid.

## 1. Svaret

Det förarna kan se — tips på Medel eller Stark, utom väg — föll från
**≈1 030 synliga tipstimmar per dygn (10-02) till 285 (10-04)** och ligger sedan
på **440–590**. Två ändringar står för det, med ett dygns mellanrum:

| # | När | Commit | Vad | Typ |
|---|---|---|---|---|
| **1** | 10-04 | `a904f9e` | **Järnvägstipsen avslutas när tåget passerar sin annonserade avgångstid** — just när de strandsatta står kvar | **Bugg, rättad här** |
| 2 | 10-03 | `64116b5` | Ny betygsskala: SL:s bussförseningar 25 → 15 poäng, Medel kräver 35, ersättningstrafik ger alltid Svag (dold som standard i appen) | Avsiktlig omkalibrering |
| 3 | 10-04 → | — | AI-granskningen av osäkra tips går inte fram (10-08: 13 av 462 `extract` lyckades) | Känd (`bearbetning-optimeringar.md` §3); rättningen ligger i `13d7ece` |

Avskrivet efter mätning: hämtningen (alla källor svarar; tåg, väg, SL och Trafiklab har
nya rader varje timme sedan 10-03 utom nattetid), geokodning (inga tips kastas för saknad koordinat; de blir
platslösa), gallringen (sju dygn *efter* sluttid) och fritextkällornas avslut
(2 121 SL-avslut, 1 återöppnat — inget fladder).

## 2. Mätningen: före och efter

**Synliga tipstimmar per dygn, Medel/Stark, utom väg** (tipsets livstid, kapad till 6 h
och räknad från tidigast 90 min före avgången):

| Dag | Tåg (Trafikverket) | SL | Trafiklab-bolagen | Västtrafik | Flyg | Färja | **Summa** |
|---|---:|---:|---:|---:|---:|---:|---:|
| 10-02 | 393 | 194 | 327 | 45 | 40 | 33 | **1 032** |
| 10-03 | 150 | 41 | 233 | 0 | 95 | 31 | **550** |
| 10-04 | 105 | 38 | 33 | 1 | 76 | 32 | **285** |
| 10-05 | 210 | 48 | 92 | 20 | 97 | 33 | **500** |
| 10-06 | 128 | 57 | 128 | 26 | 92 | 34 | **465** |
| 10-07 | 140 | 83 | 89 | 12 | 80 | 35 | **439** |
| 10-08 | 215 | 136 | 122 | 15 | 70 | 35 | **593** |

10-01 (2 777 h) är utelämnad som baslinje: den är delvis gallrad och domineras av
långlivade Trafiklab-larm. Flyg och färja är opåverkade — de har egna kedjor.

**Antal Medel/Stark-tips per dygn och hur många av dem som avslutades i förtid:**

| Dag | Tåg | varav avslutade vid avgången | SL | Trafiklab | Västtrafik |
|---|---:|---:|---:|---:|---:|
| 10-02 | 189 | 0 | 291 | 221 | 34 |
| 10-03 | 135 | 0 | 26 | 142 | 0 |
| 10-04 | 144 | 83 | 25 | 46 | 1 |
| 10-05 | 490 | **490** | 62 | 121 | 11 |
| 10-06 | 383 | **383** | 103 | 231 | 16 |
| 10-07 | 326 | **326** | 127 | 172 | 10 |
| 10-08 | 316 | **299** | 150 | 217 | 11 |

Tågen *skapar* fler Medel/Stark-tips än före 10-03, men nästan alla dör vid avgången.

## 3. Orsak 1 — järnvägstipsen dör vid avgången (bugg)

`core/sources/trafikverket_rail.py:386` frågar bara efter avgångar vars **annonserade**
tid ligger framåt:

```xml
<GT name="AdvertisedTimeAtLocation" value="$now"/>
```

Sedan `a904f9e` (10-04) avslutar `poll_rail` varje `tvr:`-tips som saknas i hämtningen
(`poll_rail.py:191-201` före den här rättningen). Ett inställt eller försenat tåg
saknas alltså i nästa runda **så fort dess avgångstid passerat** — och avslutas med
`expired_reason='source_removed'`. Men tipset är byggt för att leva efter avgången:
`platform_end()` ger det försening + 10 min, eller glappet till nästa resa + 10 min
(högst 1 h), och `_normalize()` har en egen gren för `now > when`.

Mätt på alla `tvr:`-tips avslutade sedan 10-04:

| Nivå | Avslutade | Median efter avgången | P90 | Median förlorad livstid | Förlorade tipstimmar |
|---|---:|---:|---:|---:|---:|
| Stark | 453 | 0,8 min | 1,3 min | **59 min** | 513 |
| Medel | 1 128 | 0,6 min | 1,3 min | **45 min** | 1 020 |
| Svag | 2 130 | 0,8 min | 1,3 min | 29 min | 1 019 |

Värst drabbade är de värdefullaste: `train.line_paused.long_gap` (Stark, 314 st) — ett
inställt tåg med lång väntan till nästa. Föraren ser tipset fram till avgången, och
det försvinner i samma ögonblick som resenärerna blir strandsatta. Notisen hinner gå
(push-cykeln var 30:e s, tipset syns från 90 min före), men listan och kartan är tomma
när föraren kommer fram.

**Rättningen** (`poll_rail.close_vanished`): avsluta bara tips vars avgång fortfarande
borde ha kommit med i hämtningen (`departure_at > now + 2 min`). Ett tåg som gått ur
fönstret behåller sin egen sluttid — som före 10-04. Ett tåg som slutar vara inställt
*före* avgången avslutas fortfarande direkt. Marginalen på 2 min täcker klockskillnaden
mot Trafikverkets `$now`. Testat i `core/test_rail.VanishedTests` (två av fem fallerar
utan rättningen); hela sviten grön på produktionsgrenen (1 431 tester).

Uppskattad effekt: ≈ +260 synliga tågtimmar per dygn på Medel/Stark, tillbaka till
nivån 10-01/02.

Inte gjort, möjligt nästa steg: vidga frågan till `$dateadd(-01:00:00)` så att ett
passerat tåg fortsätter uppdateras (nästa resa flyttas fram, ny beräknad tid). Ger fler
sidor per runda och rör `tip_stations`; mät sidantalet först.

## 4. Orsak 2 — omkalibreringen 10-03 (avsiktlig)

`64116b5` "Taxiläget" införde en gemensam skala i `core/taxi_context.py`:
`MEDIUM_SCORE = 35` (rad 42), `STRONG_SCORE = 60` + strandsättning, och omständigheter
(rusning, väder, ersättning) räknas bara från lägespoäng `CONTEXT_MIN_BASE = 25` (rad 50).
Fritextens lägespoäng sattes i `core/text_scoring.py:158-163`.

| Regel | Före (10-01–02) | Efter (10-03–08) | Varför |
|---|---|---|---|
| `bus.vehicle_delayed.mediumish` | 295 Medel, 43 Svag (25 p) | **6 584 Svag**, 0 Medel (15 p) | `BUS_DELAY_SCORE = 15` < 25, så omständigheterna räknas inte heller |
| `bus.vehicle_cancelled.serious` | 46 Stark | 44 Medel | 45 p, inte strandsatt → aldrig Stark |
| `train.vehicle_cancelled.replacement` | 136 Medel (41 p) | 1 643 Svag (30 p) | `final_level`: `has_alternative` → alltid Svag (rad 242) |
| `train.line_delayed` | 118 Medel | 792 Medel + 140 Stark | oförändrat värde |

Bussarna är det mesta av SL:s och Trafiklabs fall. Stickprov på det som nu är Svagt:
"Förseningar upp till 10 minuter för buss linje 725 från Tumba station 16:58",
"Avgången från Karolinska sjukhuset norra kl 16:01 … cirka 9 minuter försenad". En
buss som är 5–15 min sen ger inga körningar — resenären väntar. **Rekommendation: behåll.**
Det är den omkalibrering som var avsikten, och den stämmer med förarvärdet.

Ersättningstrafiken är ett **ägarbeslut**, inte en bugg: invariant 12 i AGENTS.md säger
att kortet ska ligga kvar i listan och bara väckningen utebli, men `final_level` gör det
Svagt och appen döljer Svaga som standard (sedan samma commit). Av raderna gäller de
flesta "Buss ersätter" och 23 "Taxi ersätter" — där har operatören redan beställt taxi.
Antingen skrivs invariant 12 om, eller så får `has_alternative` sänka till Medel i stället
för Svag. Inget ändrat här.

Övriga trösklar som briefen frågade efter: ett tåg blir tips först vid **≥ 30 min**
försening (`trafikverket_rail.py:493`), 40 p (55 p från 60 min, `scoring.py:43-45`).
Ett tåg 15 min sent kastas vid hämtningen — rätt för en förare, resenären väntar på
perrongen. Två konstanter heter `SERIOUS_DELAY_MIN` med olika värden (30 i källan, 60 i
poängen) och ingen av dem bor i `thresholds.py` (invariant 7) — teknisk skuld, inte fel.

## 5. Orsak 3 — AI-granskningen går inte fram

Osäkra tips (`confidence='low'`) kan höjas av granskningen till högst 55 (Medel). Den
lyckas inte:

| Dag | `brief` anrop / ok | `extract` anrop / ok | Felet |
|---|---|---|---|
| 10-06 | 2 823 / 0 | 176 / 23 | 429 `RESOURCE_EXHAUSTED` |
| 10-07 | 2 344 / 403 | 655 / 145 | timeout |
| 10-08 | 2 537 / 66 | 462 / 13 | 429 + timeout |

Rättningarna från `bearbetning-optimeringar.md` §3 (dagstaket räknar bara lyckade anrop,
backoff per tips i `ai_client.retry_allowed`, felpaus, beskedet bara för tips som ska
notifieras) finns i `13d7ece`. Samma commit ändrade `fleet/access.py` så att
åtkomstfönstret slog upp bolagen på UUID medan förarvägen skickar text: provkonton
fick hela flödet (färjor och flyg, en direktlänk till ett låst tips gav 200 i stället
för 403) och tio tester fallerade. Rättat i `b76c70d` (uppslagen nycklas på `str(id)`)
innan något av det gick ut.

Kvoten räcker inte ens utan stormen: nyckeln ligger på Googles gratisnivå (15 anrop
per minut och modell). Betald nyckel, eller färre anrop.

## 6. Förarvärdet: vad som borde synas

| Signal | Värde för en förare | Gör kedjan rätt? |
|---|---|---|
| Inställt tåg, lång väntan (`line_paused.long_gap`) | Högt — strandsatta på perrongen | **Nej, dör vid avgången** (orsak 1) |
| Försenat tåg ≥ 30 min | Medel–högt | **Nej, dör vid avgången** (orsak 1) |
| Flera flyg som landar inom 30 min | Högt | Ja (`flight_scoring.py`, ankomster, aldrig resenärer) |
| Färja ≥ 100 m som lägger till | Högt | Ja (AIS, 33–38 per dygn, opåverkade) |
| Hela linjen stoppad (`whole_line_stop`, 70 p) | Högt | Ja |
| Buss 5–15 min sen | Lågt | Ja, Svag sedan 10-03 |
| Enstaka inställd avgång, nästa om några min | Lågt | Ja, Svag |
| Ersättningsbuss insatt | Lågt–medel | Svag — ägarbeslut (§4) |
| Vägkö, vägarbete | Inget (de som drabbas sitter redan i bil) | Ja, kapat till 15 p, bara olyckor visas |

Kombinationslagret (`combine_signals`) är inte en flaskhals för volymen: det slår ihop
rader i listan och tar aldrig bort tips.

## 7. Genkit: spec för sammanslagna tips

Briefen bad om TypeScript. Backenden är Django och Genkit körs redan i Python
(`genkit_google_genai` bakom `core/ai_client.py`, med minuttak, backoff, kostnadslogg och
`TAXITIPS_AI=off`). Node-workern pensioneras (AGENTS §2). En andra runtime för ett AI-steg
vore två vägar ut till modellen; specen nedan går därför genom `ai_client.generate`.

Två fält i briefen strider mot invarianter och är omgjorda:

* **`driverValueScore` sätts av reglerna, inte modellen** (invariant 9: AI:n läser fakta,
  reglerna sätter poängen). Det blir `max(demand_score)` i klustret / 10.
* **Inget passagerarantal** (invariant 15, CLAUDE.md regel 4). Sammanfattningen får säga
  "tre plan landar" eller "stor station", aldrig "≈500 personer".

`urgency` behöver ingen modell: den följer av tiderna.

**Nivå 1, deterministisk (finns):** källa → `text_scoring`/`scoring` → `taxi_context` →
län/kommun (`areas.place_for`) → `combine.find` (samma tåg, samma station, närhet i km).
H3 behövs inte: `area_codes` och `combine._near` gör zonindelningen, och `h3_index` är tom.

**Nivå 2, Genkit:** bara kluster med ≥ 2 tips där minst ett är Medel/Stark och som ska
visas eller notifieras. Enskilda tips har redan sitt förarbesked (`briefs.py`).

```python
# core/tip_fusion.py -- spec, inte driftsatt
from datetime import timedelta
from enum import Enum

from pydantic import BaseModel, Field

from core import ai_client, briefs, thresholds

FUSION_MAX_PER_CYCLE = 3          # -> thresholds.py
HEADLINE_MAX_WORDS = 6


class FusionOut(BaseModel):
    """Det enda modellen skriver: ord. Inga poäng, inga tider den inte fått."""
    headline: str = Field(default="", max_length=48)
    summary: str = Field(default="", max_length=160)   # plats + vad som hänt + fönster
    used_ids: list[str] = Field(default_factory=list)  # vilka av tipsen raden bygger på


class Urgency(str, Enum):
    IMMEDIATE = "IMMEDIATE"   # något tips pågår nu
    UPCOMING = "UPCOMING"     # börjar inom FEED_HORIZON_HOURS
    MONITOR = "MONITOR"


PROMPT = """Flera störningar på samma plats. Skriv till en taxiförare, på svenska:
- headline: högst 6 ord, vad som gör platsen värd att köra till.
- summary: högst 160 tecken: var resenärerna står, vad som hänt, hur länge det gäller.
- used_ids: id för de tips du använt.
Regler: använd bara uppgifterna nedan; varje siffra och klockslag måste stå där;
skriv aldrig hur många personer; hittar du inget säkert, svara tomt.

{facts}
"""


def urgency(cluster, now) -> Urgency:
    if any(o.start_time and o.start_time <= now < o.end_time for o in cluster):
        return Urgency.IMMEDIATE
    horizon = now + timedelta(hours=thresholds.FEED_HORIZON_HOURS)
    if any(o.start_time and o.start_time <= horizon for o in cluster):
        return Urgency.UPCOMING
    return Urgency.MONITOR


def driver_value(cluster) -> int:
    return max(1, min(10, round(max(o.demand_score for o in cluster) / 10)))


def fuse(cluster, key: str, now) -> dict | None:
    """Ett sammanslaget kort, eller None -- då visas tipsen var för sig som i dag."""
    if len(cluster) < 2 or not any(o.level in ("high", "medium") for o in cluster):
        return None
    facts = "\n\n".join(f"id: {o.external_id}\n{briefs.source_text(o)}" for o in cluster)
    if key not in ai_client.retry_allowed("fuse", [key], now):
        return None
    try:
        out = ai_client.generate(
            "fuse", PROMPT.format(facts=facts), FusionOut,
            model=thresholds.AI_MODEL_EXTRACT, subject=key, timeout=thresholds.AI_BRIEF_TIMEOUT_S,
        )
    except Exception:
        return None                      # regelsvaret gäller
    headline = briefs.valid(out.headline, facts)
    summary = briefs.valid(out.summary, facts) if len(out.summary) <= 160 else None
    ids = {o.external_id for o in cluster}
    if not headline or len(headline.split()) > HEADLINE_MAX_WORDS or not set(out.used_ids) <= ids:
        return None
    return {
        "headline": headline, "summary": summary or "",
        "urgency": urgency(cluster, now).value,
        "driverValueScore": driver_value(cluster),
        "sourceEventIds": sorted({i for o in cluster for i in (o.source_event_ids or [])}),
        "tips": sorted(out.used_ids),
    }
```

`briefs.valid` gäller 90 tecken; för `summary` behövs samma sifferkontroll med 160 som tak
— bryt ut kontrollen i en funktion med längden som parameter innan det här byggs.
Resultatet sparas på `opportunity_combinations`-raden (inte på tipsen), skrivs om bara
när klustrets innehåll ändras (hash av `source_text`, som `brief_key`), och mäts med
`manage.py eval_ai` mot nya facit i `core/fixtures/golden_tips.jsonl` innan det visas i
appen (CLAUDE.md regel 6: inget halvsynligt). **Bygg det efter** att orsak 3 är löst — med
dagens kvot får inte ens förarbeskeden fram.

Bättre användning av samma kvot, i ordning (ur `bearbetning-optimeringar.md` §5): plats
och klockslag ur SL:s fritext (77 % av SL-tipsen saknar plats), sedan `ai_gate`, sedan
sammanslagningen ovan.

**Steg 1 är byggt (2026-10-09):** linje och hållplats ur fritexten med regler
för varje tips och Genkit bara för resten, en läsning per text, och minst en
rad "Därför" på varje tips — se `docs/genkit-bedomning.md`.

## 8. Efter driftsättning: så syns det

```sql
-- Andel tåg-Medel/Stark som avslutas av källan, och hur långt efter avgången.
-- Före: 100 % (10-05..07), median 0,7 min. Efter: bara tåg som försvann före avgången.
select (computed_at at time zone 'Europe/Stockholm')::date d,
  count(*) filter (where level in ('high','medium')) mh,
  count(*) filter (where level in ('high','medium') and expired_reason = 'source_removed') mh_closed,
  percentile_disc(0.5) within group (order by extract(epoch from end_time - departure_at)/60)
    filter (where expired_reason = 'source_removed') p50_min_after_dep
from opportunities where external_id like 'tvr:%' and computed_at >= now() - interval '3 days'
group by 1 order by 1;
```

Mål: tågens synliga Medel/Stark-timmar (tabellen i §2) tillbaka till ≈ 400 per dygn.

## Frågorna

```sql
-- §2 synliga tipstimmar och antal per källa och dag
with t as (
  select (computed_at at time zone 'Europe/Stockholm')::date d,
    case when external_id like 'tvr:%' then 'rail' when kind = 'road' then 'road'
         when kind in ('flight','ferry') then kind when external_id like 'sl:%' then 'SL'
         when external_id like 'vt:%' then 'Västtrafik' else 'Trafiklab' end src,
    level, end_time, computed_at, departure_at, expired_reason
  from opportunities where computed_at >= '2026-10-01' and computed_at < '2026-10-09')
select d, src, count(*) rows_written,
  count(*) filter (where level in ('high','medium')) med_high,
  round(sum(extract(epoch from greatest(interval '0', least(end_time, computed_at + interval '6 hours')
    - greatest(computed_at, coalesce(departure_at - interval '90 min', computed_at))))/3600)
    filter (where level in ('high','medium')))::int med_high_visible_h,
  count(*) filter (where level in ('high','medium') and expired_reason = 'source_removed') mh_closed_early
from t where src <> 'road' group by 1, 2 order by 2, 1;

-- §3 förlorad livstid per nivå (planerad sluttid enligt platform_end)
with t as (
  select level, extract(epoch from (end_time - departure_at))/60 after_dep,
    extract(epoch from (least(departure_at + interval '1 hour',
      case when delay_minutes is not null then departure_at + make_interval(mins => delay_minutes + 10)
           when has_alternative then departure_at + interval '30 min'
           when coalesce(next_departure_minutes, 0) > 0 then departure_at + make_interval(mins => next_departure_minutes + 10)
           else departure_at + interval '1 hour' end) - end_time))/60 lost
  from opportunities where external_id like 'tvr:%' and expired_reason = 'source_removed'
    and start_time >= '2026-10-04' and departure_at is not null)
select level, count(*), percentile_disc(0.5) within group (order by after_dep),
  percentile_disc(0.9) within group (order by after_dep),
  percentile_disc(0.5) within group (order by lost), round(sum(greatest(lost, 0))/60)
from t group by 1;

-- §4 regel och nivå före/efter
select case when start_time < '2026-10-03' then 'före' else 'efter' end, rule_id, level, count(*)
from opportunities where kind = 'transit' and start_time >= '2026-10-01' and start_time < '2026-10-09'
group by 1, 2, 3 order by 1 desc, 4 desc;

-- §1 hämtningen: timmar utan nya rader per källa, senaste 7 dygnen
-- (source_events grupperat på date_trunc('hour', created_at) mot generate_series)

-- §5 AI-vägen
select (created_at at time zone 'Europe/Stockholm')::date, purpose, count(*), count(*) filter (where ok)
from ai_call where created_at >= '2026-10-05' group by 1, 2 order by 1, 2;
```
