"""
Linje, hållplats och klockslag ur trafikbolagets egen fritext -- utan modell.

Mätt i produktion (2026-10-08, ett dygn): 3 096 av 3 316 SL-tips saknade plats,
fast texten nästan alltid säger var: "Förseningar upp till 10 minuter för buss
linje 725 från Tumba station 16:58 mot Söderby park", "Avgången från Karolinska
sjukhuset norra kl 16:01 till Sollentuna station är cirka 9 minuter försenad".
Trafikbolagen skriver efter mallar, och mallarna går att läsa med regler. Det
är gratis, deterministiskt och körs på varje tips i insamlingen (core/ingest.py).
Genkit (core/places_ai.py) läser bara det som blir kvar.

Två regler som inte får brytas:

1. **Bara strängar som står i texten.** Ett hållplatsnamn är en delsträng av
   rubriken eller beskrivningen, ordagrant (`literal()`), och ett klockslag
   eller en försening är siffror som står där. Linjens etikett ("Buss 725")
   byggs av numret i texten och färdsättet -- aldrig av en gissning.
2. **Koordinater bara ur registret** (`registry_coords`): hållplatsregistret
   (StopArea, SL och Västtrafik) och Trafikverkets stationer, exakt namn efter
   normalisering, inom tipsets eget län. Flera träffar långt ifrån varandra
   betyder att vi inte vet -- då ingen koordinat (AGENTS §6 invariant 2).
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field

# --- Klockslag och försening -------------------------------------------------

_CLOCK_RE = re.compile(r"(?<![\d:.])(\d{1,2})[:.](\d{2})(?![\d:])")
# "upp till 10 minuter", "cirka 9 minuter", "10 minuters försening",
# "försenad 10 minuter", "försenad ca. 7 minuter", "ca 8 minuter".
_DELAY_RE = re.compile(
    r"(?P<q>upp till|cirka|c:a|ca\.?|runt|omkring|drygt|minst|över)?\s*"
    r"(?:(?P<lo>\d{1,3})\s*[-–]\s*)?(?P<n>\d{1,3})\s*(?:min\b|minuter|minuters)",
    re.IGNORECASE,
)
_DELAY_CONTEXT_RE = re.compile(r"försen|sen\b|senare|förseningen", re.IGNORECASE)


def clocks(text: str) -> list[str]:
    """Klockslagen i texten, i ordning, som HH:MM. Bara giltiga tider."""
    out: list[str] = []
    for match in _CLOCK_RE.finditer(text or ""):
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour <= 23 and minute <= 59:
            value = f"{hour:02d}:{minute:02d}"
            if value not in out:
                out.append(value)
    return out


def delay(text: str) -> tuple[int, str] | None:
    """
    (minuter, kvalifikator) för förseningen texten anger, eller None.

    Kvalifikatorn är "upp till", "cirka" eller "" -- ordet som stod där, så
    att förarens rad kan säga samma sak som trafikbolaget. Bara när meningen
    talar om försening: "gäller 10 minuter" eller "gå 300 meter" är ingen.
    """
    for sentence in _sentences(text):
        if not _DELAY_CONTEXT_RE.search(sentence):
            continue
        match = _DELAY_RE.search(sentence)
        if not match:
            continue
        minutes = int(match.group("n"))
        if not 1 <= minutes <= 600:
            continue
        if match.group("lo"):
            # "20-30 minuter": båda talen, som texten säger dem.
            return minutes, f"mellan {int(match.group('lo'))} och"
        q = (match.group("q") or "").lower().rstrip(".")
        qualifier = {"upp till": "upp till", "cirka": "cirka", "ca": "cirka", "c:a": "cirka",
                     "runt": "cirka", "omkring": "cirka"}.get(q, "")
        return minutes, qualifier
    return None


# --- Linjen --------------------------------------------------------------------

_MODE_NOUN = {"bus": "Buss", "tram": "Spårvagn", "metro": "Tunnelbana", "train": "Tåg", "boat": "Båt"}

# Namngivna banor: namnet är linjen ("Tvärbanan", "Lidingöbanan 21").
_NAMED_LINE_RE = re.compile(
    r"\b(Tvärbanan|Lidingöbanan|Nockebybanan|Saltsjöbanan|Roslagsbanan|Spårväg City|Djurgårdslinjen)"
    r"(?:\s+(?:linje\s+)?(\d{1,2}))?\b",
    re.IGNORECASE,
)
_METRO_COLOR_RE = re.compile(r"\b(?:tunnelbanans\s+)?(gröna|röda|blå)\s+linje(?:n)?\b", re.IGNORECASE)
# Tåg med nummer: "Pågatåg 1612", "Västtågen 7241", "Tåg nr 382", "pendeltåg 2245".
_TRAIN_NO_RE = re.compile(
    r"\b(Pågatåg(?:en)?|Västtåg(?:en)?|Krösatåg(?:en)?|Öresundståg(?:et)?|Upptåg(?:et)?|"
    r"Mälartåg(?:et)?|Norrtåg(?:et)?|pendeltåg(?:et)?|Vy Tåg|SJ|Snälltåget|tåg(?:et)?(?:\s+nr\.?)?)"
    r"\s+(\d{2,5})\b",
    re.IGNORECASE,
)
# "buss linje 725", "blåbuss linje 175", "Stadsbuss Malmö linje 11", "spårvagn 7",
# "spårvagnslinje 3", "tunnelbanelinje 17", "pendeltåg linje 41", "linje 26M".
_KIND_LINE_RE = re.compile(
    r"\b(?P<kind>blåbuss|stadsbuss|regionbuss|expressbuss|ersättningsbuss|närtrafik|buss|"
    r"spårvagn(?:slinje)?|tunnelbane(?:linje|tåg)?|pendeltåg|båt(?:linje)?|pendelbåt)"
    r"(?:\s+[A-ZÅÄÖ][a-zåäö]+)?(?:\s+linje|\s+nr\.?)?\s+(?P<num>\d{1,4}[A-ZÅÄÖ]?)\b",
    re.IGNORECASE,
)
# "Linje S" (Värmlandstrafik): en ensam VERSAL är också ett linjenamn -- men
# aldrig en gemen ("linjen i båda riktningar").
_LINE_RE = re.compile(r"\blinje(?:rna|n)?\s+(?P<num>\d{1,4}[A-ZÅÄÖ]?|(?-i:[A-ZÅÄÖ]))\b", re.IGNORECASE)

_KIND_LABEL = {
    "blåbuss": "Blåbuss", "ersättningsbuss": "Ersättningsbuss", "närtrafik": "Närtrafik",
    "spårvagn": "Spårvagn", "spårvagnslinje": "Spårvagn", "tunnelbane": "Tunnelbana",
    "tunnelbanelinje": "Tunnelbana", "tunnelbanetåg": "Tunnelbana", "pendeltåg": "Pendeltåg",
    "båt": "Båt", "båtlinje": "Båt", "pendelbåt": "Pendelbåt",
}


def line_label(text: str, *, route_label: str | None = None, mode: str = "") -> str:
    """
    Linjen som en förare säger den: "Buss 725", "Pågatåg 1612", "Tvärbanan".

    SL:s och Västtrafiks strukturerade linjefält (`route_label`) vinner när det
    finns; annars läses linjen ur texten. Numret står alltid i källan, ordet
    framför kommer ur texten eller färdsättet. Tom sträng när inget står.
    """
    label = (route_label or "").strip()
    # Västtrafik sätter "TÅG" som linjebeteckning på alla tåg: ingen linje.
    if label.upper() in ("TÅG", "BUSS", "SPÅRVAGN", "BÅT", "FÄRJA", "TUNNELBANA"):
        label = ""
    if label:
        if re.fullmatch(r"[A-ZÅÄÖ]{0,3}\d{1,4}[A-ZÅÄÖ]?", label):
            noun = _MODE_NOUN.get(mode)
            return f"{noun} {label}" if noun else f"Linje {label}"
        return label[:40]
    text = text or ""
    match = _NAMED_LINE_RE.search(text)
    if match:
        name = match.group(1)
        name = name[:1].upper() + name[1:]
        return f"{name} {match.group(2)}" if match.group(2) else name
    match = _METRO_COLOR_RE.search(text)
    if match:
        return f"Tunnelbanans {match.group(1).lower()} linje"
    match = _TRAIN_NO_RE.search(text)
    if match:
        kind = match.group(1)
        kind = re.sub(r"\s+nr\.?$", "", kind, flags=re.IGNORECASE)
        kind = re.sub(r"(?i)^(pågatåg|västtåg|krösatåg)en$", r"\1", kind)
        kind = re.sub(r"(?i)^(öresundståg|upptåg|mälartåg|norrtåg|pendeltåg|tåg)et$", r"\1", kind)
        kind = kind[:1].upper() + kind[1:]
        return f"{kind} {match.group(2)}"
    match = _KIND_LINE_RE.search(text)
    if match:
        kind = match.group("kind").lower()
        label_kind = _KIND_LABEL.get(kind, "Buss")
        return f"{label_kind} {match.group('num')}"
    match = _LINE_RE.search(text)
    if match:
        noun = _MODE_NOUN.get(mode)
        return f"{noun} {match.group('num')}" if noun else f"Linje {match.group('num')}"
    return ""


# --- Hållplatser och stationer -----------------------------------------------

# Ord som avslutar ett namn. Ett hållplatsnamn kan ha små bokstäver efter
# första ordet ("Karolinska sjukhuset norra", "Hässelby strand", "Knutby skola"),
# så namnet läses ord för ord tills något av de här kommer.
_STOP_WORDS = frozenset("""
kl kl. klockan mot till från på pga p.g.a. p.g.a är blir och eller beräknas med för i
samt har kan ca ca. cirka via sedan stannar trafikerar läge inställd inställt inställda
försenad försenat försenade avgår går ersätts idag under efter vid mellan det den som
enligt hela delvis upp ingen inga trafiken bussen tåget tågen bussarna linje linjen
resenärer resande vi se på grund orsaken detta beror gäller tills åter igen nu
pågår stopp stoppad stoppat avstängd avstängt avstängda indragen indragna flyttas flyttad
flyttade flyttat hänvisas om stängd stängda stängs tillfälligt tillfällig delinställd
delinställda delinställt ersätter riskerar saknas trafikeras ska skall körs kör syns
""".split())

# Ett "namn" som är ett vanligt ord, en rubrik eller en tidsangivelse.
_NOT_A_PLACE_RE = re.compile(
    r"^(inställ\w*|övriga avgångar|buss\w*|ersättnings\w*|försening\w*|trafik\w*|"
    r"ny avgångstid|tågbyte|invänta|okänd|ingen|tåg\w*|linje\w*|resenär\w*|vi|sl|"
    r"detta|den|det|en|ett|alla|samtliga|hållplats\w*|station|stationen|perrong\w*|"
    r"spår\w*|läge|måndag\w*|tisdag\w*|onsdag\w*|torsdag\w*|fredag\w*|lördag\w*|söndag\w*|"
    r"januari|februari|mars|april|maj|juni|juli|augusti|september|oktober|november|"
    r"december|idag|i dag|ikväll|natten|morgonen|kvällen|tunnelbana\w*|spårvagn\w*|"
    r"pendeltåg\w*|regionbuss\w*|stadsbuss\w*|blåbuss\w*|resecentrum|centrum|norra|"
    r"södra|östra|västra|sök|läs|mer|info|information|se|obs|nytt|ny|kommande)$",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[\wÅÄÖåäöÉéÜü'’/&-]+\.?|[,.;:!?()\n–-]")
_UPPER_START_RE = re.compile(r"^[A-ZÅÄÖÉÜ]")
_ORT_RE = re.compile(r"^[A-ZÅÄÖÉÜ][\wåäöéü-]+$")
_MAX_NAME_TOKENS = 6

# Var ett namn börjar, och vilken roll det har. "till" räknas bara som mål i en
# mening som redan har ett "från" ("Avgången från X kl 16:01 till Y") --
# annars är det "hänvisas till hållplats Z", "till och med", "tills vidare".
_ORIGIN_RE = re.compile(r"\b(?:från|fr\.)\s+(?:hållplats(?:en)?\s+)?(?!och med\b|kl\b|klockan\b|\d)", re.IGNORECASE)
# "Linje 2 Ilanda bytespunkt, Karlstad kl 21:54 mot ...", "Linje 900 Skoghall Centrum
# kl 21:43": Värmlandstrafiks mall, avgångens hållplats direkt efter linjenumret.
# SL:s korta form "823 Tyresö centrum försenad cirka 12 min" har linjenumret först.
_LINE_ORIGIN_RE = re.compile(r"(?:\b[Ll]inje\s+(?:\d{1,4}[A-ZÅÄÖ]?|[A-ZÅÄÖ])|^\s*\d{1,4}[A-Z]?)\s+(?=[A-ZÅÄÖ])")
_AFTER_LINE_ORIGIN_RE = re.compile(r"\s+(?:kl\b|klockan\b|\d{1,2}[:.]\d{2}|försenad\b|inställd\b|[-–]\s)")
_TARGET_RE = re.compile(r"\bmot\s+(?:hållplats(?:en)?\s+)?", re.IGNORECASE)
_TILL_RE = re.compile(r"\btill\s+(?!och med\b|cirka\b|ca\b|nästa\b|hållplats|alternativ|övriga|\d)", re.IGNORECASE)
# Inte "på": "cirka 1 km västerut, på Tornavägen" är gatan där ersättningshållplatsen står.
_AT_RE = re.compile(r"\b(?:vid|hållplats(?:en|erna)?)\s+(?:hållplats(?:en)?\s+)?", re.IGNORECASE)
# Resten av en mening efter "hänvisas till ..." handlar om alternativet, inte om
# platsen där störningen är: "Hänvisning till ersättningsbuss från hållplats Telefonplan".
_REFERRAL_RE = re.compile(r"hänvis|resenärer kan|vi hänvisar|istället|i stället", re.IGNORECASE)
_BETWEEN_RE = re.compile(r"\bmellan\s+(?:hållplats(?:erna)?\s+)?", re.IGNORECASE)
# "Linköpings resecentrum - Kisa resecentrum kl 18:50", "Tåget är inställt Malmö
# Hyllie - Malmö C.", "Linje 8 Sjöstad, Karlstad - Grava kyrka, Karlstad kl 10:03".
_DASH_RE = re.compile(r"\s[-–]\s")
_DASH_LEFT_BOUNDARY_RE = re.compile(
    r"(?:^|[.:!?\n]\s*|\bsträckan\s+|\binställ[dt]a?\s+|\b[Ll]inje\s+(?:\d{1,4}[A-ZÅÄÖ]?|[A-ZÅÄÖ])\s+|"
    r"\bförsenad\s+|\bTåget är inställt\s+|\b[Tt]rafik(?:en)?\s+)",
)


def _scan_name(text: str, start: int) -> tuple[str, int] | None:
    """
    Läser ett namn som börjar på `start`: ord för ord tills ett stoppord, ett
    klockslag eller ett skiljetecken. Returnerar (namn, slutposition) -- namnet
    är en ordagrann delsträng av texten.
    """
    tokens = list(_TOKEN_RE.finditer(text, start))
    if not tokens or tokens[0].start() - start > 1:
        return None
    first = tokens[0].group(0)
    if not _UPPER_START_RE.match(first) or first.lower().rstrip(".") in _STOP_WORDS:
        return None
    end = tokens[0].end()
    count = 1
    i = 1
    while i < len(tokens) and count < _MAX_NAME_TOKENS:
        tok = tokens[i]
        word = tok.group(0)
        # Bara ett mellanslag mellan orden: "Tumba station", inte "Tumba\n\nstation".
        gap = text[end:tok.start()]
        if word == ",":
            # Värmlandstrafik och UL skriver "Ilanda bytespunkt, Karlstad kl 21:54":
            # orten efter kommat hör till namnet när den följs av tid eller riktning.
            if i + 1 < len(tokens) and _ORT_RE.match(tokens[i + 1].group(0)):
                after = text[tokens[i + 1].end():tokens[i + 1].end() + 12].lower()
                if re.match(r"\s*(kl\b|klockan\b|mot\b|till\b|är\b|beräknas\b|[-–]\s|\d{1,2}[:.]\d{2}|\.|$)", after):
                    end = tokens[i + 1].end()
                    i += 2
                    count += 1
                    continue
            break
        if gap not in (" ",) or not re.match(r"[\wÅÄÖåäöÉé]", word):
            break
        bare = word.lower().rstrip(".")
        if bare in _STOP_WORDS:
            break
        if _CLOCK_RE.fullmatch(word) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", word):
            break
        if word.isdigit() and (len(word) > 3 or text[tok.end():tok.end() + 1] in (":", ".")):
            break
        end = tok.end()
        count += 1
        i += 1
    name = text[start:end].strip().rstrip(".")
    return (name, end) if name else None


def _clean(name: str) -> str:
    """Tar bort lägesangivelser och parenteser ur ett namn -- men bara i slutet."""
    name = re.sub(r"\s+\(?läge\s+[A-ZÅÄÖ0-9]{1,2}\)?$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+\(\d+\)$", "", name)
    name = name.strip(" ,.;:-–")
    return name


def _acceptable(name: str) -> bool:
    if not name or len(name) < 2 or len(name) > 60:
        return False
    first = name.split()[0].rstrip(",")
    if _NOT_A_PLACE_RE.match(name) or _NOT_A_PLACE_RE.match(first) and len(name.split()) == 1:
        return False
    if re.fullmatch(r"[\d\s:.,-]+", name):
        return False
    return True


@dataclass
class TextFacts:
    """Det reglerna läste ur texten. Tomma fält = texten säger inget."""

    line: str = ""
    origin: str = ""
    destination: str = ""
    stops: list[str] = field(default_factory=list)
    clocks: list[str] = field(default_factory=list)
    # Klockslaget som hör till avgångens hållplats ("från Tumba station 16:58",
    # "Avgången kl 8:53 från Knutby skola") -- inte vilket klockslag som helst:
    # "stopp sedan klockan 08:30" är ingen avgång.
    departure_clock: str = ""
    delay_minutes: int | None = None
    delay_qualifier: str = ""

    @property
    def station(self) -> str:
        """Platsen där resenärerna står: avgångens hållplats, annars första nämnda."""
        if self.origin:
            return self.origin
        for stop in self.stops:
            if stop != self.destination:
                return stop
        return ""

    @property
    def places(self) -> list[str]:
        """Platserna i läsordning: där resenärerna står först, målet sist."""
        out: list[str] = []
        for name in [self.origin, *self.stops, self.destination]:
            if name and not any(name.lower() == p.lower() for p in out):
                out.append(name)
        return out


def _sentences(text: str) -> list[str]:
    # "Linje 8 ... ca. 7 minuter." -- punkten efter "ca" avslutar ingen mening.
    return [s for s in re.split(r"(?<![Cc]a\.)(?<!\bkl\.)(?<=[.!?\n])\s+", text or "") if s.strip()]


def _dash_pairs(sentence: str) -> list[tuple[str, str, int]]:
    pairs = []
    for dash in _DASH_RE.finditer(sentence):
        left_text = sentence[: dash.start()]
        boundary = None
        for match in _DASH_LEFT_BOUNDARY_RE.finditer(left_text):
            boundary = match
        if boundary is None:
            continue
        left = _clean(left_text[boundary.end():].strip())
        right = _scan_name(sentence, dash.end())
        if not right:
            continue
        right_name = _clean(right[0])
        # Båda sidor ska vara namn: "08:00 - 10:00" eller "kl 4:00 - 22 september" är inga.
        if not (_acceptable(left) and _acceptable(right_name)):
            continue
        if len(left.split()) > _MAX_NAME_TOKENS + 1 or any(w.lower() in _STOP_WORDS for w in left.split()):
            continue
        if not _UPPER_START_RE.match(left):
            continue
        pairs.append((left, right_name, right[1]))
    return pairs


_CLOCK_AFTER_RE = re.compile(r"^,?\s*(?:kl\.?|klockan)?\s*(\d{1,2})[:.](\d{2})(?![\d:])", re.IGNORECASE)
_CLOCK_BEFORE_RE = re.compile(
    r"(?:kl\.?|klockan)\s*(\d{1,2})[:.](\d{2})"
    r"(?:,?\s+är\s+(?:inställ\w*|försena\w*|delinställ\w*)(?:\s+och\s+[^.]{0,60}?)?)?\s*$",
    re.IGNORECASE,
)


def _clock_value(match) -> str:
    if not match:
        return ""
    hour, minute = int(match.group(1)), int(match.group(2))
    return f"{hour:02d}:{minute:02d}" if hour <= 23 and minute <= 59 else ""


def extract(header: str | None, description: str | None, *, route_label: str | None = None,
            mode: str = "") -> TextFacts:
    """Rubrik + beskrivning -> linje, hållplatser, klockslag och försening."""
    header = header or ""
    description = description or ""
    text = f"{header}\n{description}"
    facts = TextFacts(line=line_label(text, route_label=route_label, mode=mode), clocks=clocks(text))
    found_delay = delay(text)
    if found_delay:
        facts.delay_minutes, facts.delay_qualifier = found_delay

    def add_stop(name: str):
        name = _clean(name)
        if _acceptable(name) and not any(name.lower() == s.lower() for s in facts.stops):
            facts.stops.append(name)

    def names(sentence: str, pattern: re.Pattern):
        """Namnen efter varje träff, utom i meningens hänvisningsdel."""
        for match in pattern.finditer(sentence):
            if _REFERRAL_RE.search(sentence[: match.start()]):
                return
            scanned = _scan_name(sentence, match.end())
            if scanned and _acceptable(_clean(scanned[0])):
                yield scanned

    # Beskrivningen först: den är fullständigare än rubriken, som ofta är en
    # förkortning av samma mening.
    for part in (description, header):
        for sentence in _sentences(part):
            has_origin = False
            def departure_at(start: int, end: int):
                if facts.departure_clock:
                    return
                facts.departure_clock = (
                    _clock_value(_CLOCK_AFTER_RE.match(sentence[end:]))
                    or _clock_value(_CLOCK_BEFORE_RE.search(sentence[:start]))
                )

            for match in _ORIGIN_RE.finditer(sentence):
                if _REFERRAL_RE.search(sentence[: match.start()]):
                    break
                scanned = _scan_name(sentence, match.end())
                if not scanned or not _acceptable(_clean(scanned[0])):
                    continue
                has_origin = True
                if not facts.origin:
                    facts.origin = _clean(scanned[0])
                if facts.origin.lower() == _clean(scanned[0]).lower():
                    departure_at(match.start(), scanned[1])
                add_stop(scanned[0])
            for name, end in names(sentence, _LINE_ORIGIN_RE):
                if _AFTER_LINE_ORIGIN_RE.match(sentence[end:]):
                    has_origin = True
                    if not facts.origin:
                        facts.origin = _clean(name)
                        departure_at(end, end)
                    add_stop(name)
            for name, end in names(sentence, _BETWEEN_RE):
                if not facts.origin and _CLOCK_AFTER_RE.match(sentence[end:]):
                    # "mellan Tjärhovsplan kl 20:04 och Tanto": avgången från den första.
                    facts.origin = _clean(name)
                    departure_at(end, end)
                add_stop(name)
                och = re.match(
                    r"(?:\s+(?:kl\.?|klockan)?\s*\d{1,2}[:.]\d{2})?\s+och\s+(?:hållplats(?:en)?\s+)?",
                    sentence[end:], re.IGNORECASE,
                )
                if och:
                    second = _scan_name(sentence, end + och.end())
                    if second:
                        add_stop(second[0])
            referral = _REFERRAL_RE.search(sentence)
            scope = sentence[: referral.start()] if referral else sentence
            for left, right, right_end in _dash_pairs(scope):
                if not facts.origin:
                    facts.origin = left
                if left == facts.origin:
                    # "Linköpings resecentrum - Kisa resecentrum kl 18:50": turens avgång.
                    after_left = re.search(re.escape(left) + r"\s*", scope)
                    if after_left:
                        departure_at(after_left.start(), after_left.end())
                    departure_at(right_end, right_end)
                add_stop(left)
                if not facts.destination:
                    facts.destination = right
            for name, _end in names(sentence, _AT_RE):
                add_stop(name)
            for name, _end in names(sentence, _TARGET_RE):
                if not facts.destination:
                    facts.destination = _clean(name)
            if has_origin:
                for name, _end in names(sentence, _TILL_RE):
                    if not facts.destination:
                        facts.destination = _clean(name)

    # Målet är inte där resenärerna står: det ligger sist i platserna.
    facts.stops = [s for s in facts.stops if s.lower() != facts.destination.lower()]
    return facts


def literal(value: str, text: str) -> bool:
    """Står strängen ordagrant i texten (skiftläge och blanksteg oräknade)?"""
    if not value:
        return False
    norm = lambda s: re.sub(r"\s+", " ", s or "").strip().lower()  # noqa: E731
    return norm(value) in norm(text)


def text_key(header: str | None, description: str | None) -> str:
    """
    Nyckeln för "samma meddelande": SL publicerar ofta samma text under tre
    external_id (en per påverkad linjevariant och källa). En modelläsning per
    text, inte per rad. 40 tecken, som Opportunity.rule_key.
    """
    norm = re.sub(r"\s+", " ", f"{header or ''}\n{description or ''}").strip().lower()
    return hashlib.sha1(f"text1|{norm}".encode()).hexdigest()


# --- Koordinater, bara ur registret ------------------------------------------

# Två träffar på samma namn längre isär än så är två olika platser ("Mörby" i
# Danderyd och i Nynäshamn): då vet vi inte vilken och sätter ingen koordinat.
SAME_PLACE_KM = 1.5
_REGISTRY_TTL_S = 6 * 60 * 60
_registry: dict | None = None
_registry_loaded_at = 0.0


def reset_registry() -> None:
    global _registry, _registry_loaded_at
    _registry, _registry_loaded_at = None, 0.0


def _norm_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name or "").strip().lower()
    return name.strip(" ,.")


def _load_registry() -> dict:
    global _registry, _registry_loaded_at
    if _registry is not None and time.monotonic() - _registry_loaded_at < _REGISTRY_TTL_S:
        return _registry
    from core.models import Station, StopArea

    stops: dict[tuple[str, str], list[tuple[float, float]]] = {}
    rail: dict[str, list[tuple[float, float]]] = {}
    try:
        for operator, name, lat, lon in StopArea.objects.values_list("operator", "name", "lat", "lon"):
            if name and lat is not None and lon is not None:
                stops.setdefault((operator, _norm_name(name)), []).append((lat, lon))
        for name, lat, lon in Station.objects.values_list("name", "lat", "lon"):
            if name and lat is not None and lon is not None:
                rail.setdefault(_norm_name(name), []).append((lat, lon))
    except Exception:
        pass  # registret saknas (omigrerad databas): inga koordinater, inget fel
    _registry, _registry_loaded_at = {"stops": stops, "rail": rail}, time.monotonic()
    return _registry


def _variants(name: str) -> list[str]:
    """Namnet som registret kan ha det: "Tumba station" heter "Tumba" hos SL."""
    base = _norm_name(_clean(name))
    out = [base]
    if "," in base:
        out.append(base.split(",")[0].strip())
    for suffix in (" station", " stn", " tågstation", " pendeltågsstation"):
        if base.endswith(suffix):
            out.append(base[: -len(suffix)].strip())
    no_paren = re.sub(r"\s*\([^)]*\)", "", base).strip()
    if no_paren != base:
        out.append(no_paren)
    seen, unique = set(), []
    for v in out:
        if v and v not in seen:
            seen.add(v)
            unique.append(v)
    return unique


def registry_coords(name: str, region: str | None) -> tuple[float, float] | None:
    """
    Koordinaten för ett hållplats- eller stationsnamn, eller None.

    Exakt namn (efter normalisering) i SL:s/Västtrafiks hållplatsregister för
    tipsets eget bolag, annars i Trafikverkets stationsregister -- och bara
    träffar inom tipsets län. Flera träffar som inte är samma plats: None.
    """
    from core.geo import _outside_market, haversine_km

    if not name:
        return None
    region = (region or "").lower()
    reg = _load_registry()
    operator = region if region in ("sl", "vt") else None
    for variant in _variants(name):
        hits: list[tuple[float, float]] = []
        if operator:
            hits = list(reg["stops"].get((operator, variant), []))
        if not hits:
            hits = list(reg["rail"].get(variant, []))
        hits = [h for h in hits if not _outside_market(h[0], h[1], region)]
        if not hits:
            continue
        first = hits[0]
        if any(haversine_km(first[0], first[1], h[0], h[1]) > SAME_PLACE_KM for h in hits[1:]):
            return None  # samma namn på två platser: vi vet inte vilken
        return first
    return None
