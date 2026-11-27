"""
Säljmejlens texter (fleet/outreach.py skickar dem).

**Tre mycket korta mejl i samma tråd.** Skrivna som ett vanligt mejl från en
person, inte som ett nyhetsbrev: ingen logga, inga bilder, en länk. Varje mejl
ska gå att läsa på tio sekunder.

**Länken går till appen, inte till ett formulär.** taxitips.se/appen skickar
en iPhone till App Store och en Android till Google Play; vid en dator visar
sidan båda butikerna och en QR-kod. Kontot skapas sedan i appen, där provet
också används.

**En bild, inte en funktionslista.** Mejlen berättar om ett ögonblick som
varje taxiägare känner igen -- perrongen full av folk, bilen på fel ställe --
och säger sedan en sak om vad appen gör åt det. Datakällor, tipsstyrkor och
annat som hör hemma på webbplatsen står inte här.

**Helst något som hände nyss, där mottagaren kör.** Finns ett inställt tåg i
bolagets län de senaste dagarna, som appen skickade ett tips om
(outreach.local_event), börjar mejlet med det: "I går klockan 21:21 ställdes ett tåg
in från Triangeln." Det är sant, det är deras trakt, och det står inte i
hundra andra mejl. Annars används en av de tre allmänna bilderna.

**Ett vanligt mejl, inte ett utskick.** Ingen knapp, ingen färg, ingen logga:
en länk i texten och en signatur som i ett mejl man skriver själv. Ämnesraden
är en fråga om just deras bilar, och man kan svara med ett ord ("visa").

**Inga siffror vi inte kan stå för.** Texterna säger vad provet är (en månad,
en bil, inget kort -- samma som taxitips.se), inte vad ett bolag "tjänar".
Tipsexemplet i mejl 2 är det som står på startsidan.

**Avsändaren ska framgå och det ska gå att tacka nej** (marknadsföringslagen
19-20 §§). Sista stycket säger vem som står bakom, var adressen kommer ifrån
och hur man avregistrerar sig. Det stycket får inte tas bort ur en mall.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from django.conf import settings

APP_PATH = "/appen"
PRIVACY_PATH = "/privacy"

# Antal mejl i serien. outreach.STEPS styr när de går.
STEP_COUNT = 3


@dataclass(frozen=True)
class Context:
    company: str
    place: str          # "Malmö" eller "Skåne län"; tomt om okänt
    first_name: str     # tomt = "Hej,"
    unsubscribe_url: str
    campaign: str = "saljmejl"
    # Vilken öppningsbild mottagaren får (0-2). Samma i hela tråden.
    variant: int = 0
    # Bolagets storlek: SOLO, FLEET eller LARGE. Styr tilltal och erbjudande.
    size: str = "fleet"
    # Ett inställt tåg i bolagets län som appen tipsade om; None = allmän bild.
    event: "LocalEvent | None" = None
    # Vilket mejl i serien (1-3). Sätts av render(); syns i länkens utm_medium.
    step: int = 1


@dataclass(frozen=True)
class LocalEvent:
    when: str       # "i dag", "i går", "i tisdags"
    clock: str      # "21:21"
    station: str    # "Triangeln"
    title: str      # tipset som föraren såg
    county: str     # "Skåne län"


# Exemplet i adminwebben och i test-send när länet inte har något färskt.
SAMPLE_EVENT = LocalEvent(
    when="i går", clock="21:21", station="Triangeln",
    title="Öresundståg 1132 21:21 är inställt från Triangeln", county="Skåne län",
)


# Tre tilltal, efter hur många bilar bolaget har (CRM-segmentet).
#
# * SOLO (1-2 bilar): ägaren kör själv. "Du", och bilden är förarsätet.
# * FLEET (3-9 bilar, eller okänd storlek): ägaren har förare. "Ni" och
#   "era förare". Det är också det säkra valet när vi inte vet.
# * LARGE (10+ bilar eller beställningscentral): den som läser kör inte själv
#   och bestämmer sällan ensam. Erbjudandet är en visning på tio minuter i
#   första hand, provet i andra.
SOLO, FLEET, LARGE = "solo", "fleet", "large"
SIZES = (SOLO, FLEET, LARGE)
SIZE_LABEL = {SOLO: "1–2 bilar", FLEET: "3–9 bilar", LARGE: "10+ bilar"}


def site() -> str:
    return (getattr(settings, "OUTREACH_SITE_BASE", "") or "https://taxitips.se").rstrip("/")


def app_url(ctx: Context) -> str:
    # utm_* säger bara vilken kampanj länken kom ifrån -- ingen mottagare pekas ut.
    return f"{site()}{APP_PATH}?utm_source=mejl&utm_medium=steg{ctx.step}&utm_campaign={ctx.campaign}"


def sender_name() -> str:
    """Tomt om ingen avsändare är inlagd; outreach.enabled() släpper då inte iväg något."""
    return (getattr(settings, "OUTREACH_SENDER_NAME", "") or "").strip()


def _signature() -> str:
    title = (getattr(settings, "OUTREACH_SENDER_TITLE", "") or "").strip()
    lines = [sender_name()] if sender_name() else []
    lines.append(f"{title}, Taxi Tips" if title else "Taxi Tips")
    phone = (getattr(settings, "OUTREACH_SENDER_PHONE", "") or "").strip()
    if phone:
        lines.append(phone)
    return "\n".join(lines)


def _footer(ctx: Context) -> str:
    company_line = (getattr(settings, "OUTREACH_COMPANY_LINE", "") or "A2M Tech AB, Malmö").strip()
    return (
        f"Taxi Tips drivs av {company_line}. Jag hittade er adress i öppna "
        "företagsregister. Vill du inte ha fler mejl? Svara \"nej tack\" "
        f"eller klicka här: {ctx.unsubscribe_url}\n"
        f"Så hanterar vi uppgifter: {site()}{PRIVACY_PATH}"
    )


def _short_company(name: str) -> str:
    """ "Ranj Taxi AB" -> "Ranj Taxi": så säger man när man hälsar på ett bolag."""
    return re.sub(r"\s+(AB|HB|KB|Kommanditbolag|Handelsbolag)$", "", name or "").strip()


def _greeting(ctx: Context, *, again: bool = False) -> str:
    """
    Förnamnet när vi är säkra på det, annars bolaget. "Hej Ranj Taxi," är
    fortfarande skrivet till någon; ett naket "Hej," är skrivet till alla.
    """
    word = "Hej igen" if again else "Hej"
    if ctx.first_name:
        return f"{word} {ctx.first_name},"
    short = _short_company(ctx.company)
    if short and len(short) <= 32 and short.lower() != "ert bolag":
        return f"{word} {short},"
    return f"{word},"


def _where(ctx: Context) -> str:
    return f" i {ctx.place}" if ctx.place else ""


def subject(ctx: Context) -> str:
    """
    Samma för hela tråden (uppföljningarna får "Re: " framför ämnet som gick i
    första mejlet, se outreach.send_step). Därför bara bolagets ort, aldrig
    dagens händelse.
    """
    if ctx.size == SOLO:
        return f"Fråga om din bil{_where(ctx)}"
    return f"Fråga om era bilar{_where(ctx)}"


def _offer(ctx: Context) -> str:
    you = "Du" if ctx.size == SOLO else "Ni"
    return (
        f"Första månaden kostar inget. {you} behöver inget kort. "
        f"Hämta appen här:\n{app_url(ctx)}"
    )


def _reply_ask(ctx: Context) -> str:
    return 'Eller svara "visa", så visar jag hur det ser ut.'


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


# Tre öppningsbilder när länet inte har någon färsk händelse. Hundra likadana
# mejl om dagen ser ut som ett massutskick för ett skräppostfilter; tre
# varianter gör det inte, och ingen av dem är mindre sann än de andra.
_SCENES = (
    "Ett tåg ställs in en kväll. Många står på stationen och vill hem.",
    "Sista planet landar sent en kväll. Inga bussar går. Alla vill hem.",
    "En konsert slutar klockan tio. Alla går ut på gatan samtidigt.",
)


def _opening(ctx: Context) -> str:
    event = ctx.event
    if event:
        return (
            f"{_sentence(event.when)} klockan {event.clock} ställdes ett tåg in från "
            f"{event.station}. Då behöver många taxi på en gång."
        )
    return _SCENES[ctx.variant % len(_SCENES)]


def _step1(ctx: Context) -> str:
    seen = (
        "Taxi Tips såg det direkt och skickade ett tips i appen."
        if ctx.event else "Appen Taxi Tips säger till när många behöver taxi."
    )
    if ctx.size == SOLO:
        middle = [
            f"{seen} Du ser var och varför. Då står du där kunderna är.",
            f"Vill du prova med din bil{_where(ctx)}? " + _offer(ctx),
            _reply_ask(ctx),
        ]
    elif ctx.size == LARGE:
        middle = [
            f"{seen} Era förare ser var och varför. Hur många av era bilar står rätt just då?",
            f"Vill ni på {ctx.company} se det? Svara på mejlet, så visar jag det "
            "på tio minuter. Eller prova med en bil. " + _offer(ctx),
        ]
    else:
        middle = [
            f"{seen} Föraren ser var och varför. Då står bilen där kunderna är.",
            f"Vill ni på {ctx.company} prova med en bil{_where(ctx)}? " + _offer(ctx),
            _reply_ask(ctx),
        ]
    return "\n\n".join([_greeting(ctx), _opening(ctx), *middle, "Vänliga hälsningar\n" + _signature()])


DEFAULT_TIP = "Avgången 18:42 från Uppsala C är inställd. Nästa avgång 19:30."


def _step2(ctx: Context) -> str:
    phone = "din telefon" if ctx.size == SOLO else "förarens telefon"
    if ctx.event:
        intro, tip = f"Så här såg ett tips i {ctx.event.county} ut {ctx.event.when}:", ctx.event.title
    else:
        intro, tip = f"Så här ser ett tips ut i {phone}:", DEFAULT_TIP
    if ctx.size == SOLO:
        ask = "Du skapar kontot i appen. " + _offer(ctx)
    elif ctx.size == LARGE:
        ask = (
            "Ska jag visa det på tio minuter? Svara på mejlet. Ni kan också prova "
            "med en bil. " + _offer(ctx)
        )
    else:
        ask = "Ni skapar kontot i appen. " + _offer(ctx)
    return "\n\n".join([
        _greeting(ctx, again=True),
        intro,
        f'"{tip}"',
        "Den som ser det först kommer dit först.",
        ask,
        "Vänliga hälsningar\n" + _signature(),
    ])


def _step3(ctx: Context) -> str:
    if ctx.size == SOLO:
        helps, start, talk = "hjälper dig att hitta rätt", "Du kan börja när du vill", "Vill du"
    else:
        helps, start, talk = "hjälper era förare att hitta rätt", "Ni kan börja när ni vill", "Vill ni"
    return "\n\n".join([
        _greeting(ctx),
        "Det här är mitt sista mejl om Taxi Tips. Passar det inte nu, hör jag inte av mig igen.",
        f"En förare vet inte var nästa kund står. Taxi Tips {helps}.",
        f"{talk} hellre prata? Svara med ett telefonnummer, så ringer jag.",
        f"{start}. Första månaden kostar inget:\n{app_url(ctx)}",
        "Vänliga hälsningar\n" + _signature(),
    ])


_BODIES = {1: _step1, 2: _step2, 3: _step3}


def render(step: int, ctx: Context, *, thread_subject: str = "") -> tuple[str, str]:
    """
    (ämne, text) för steg 1-3. Uppföljningarna svarar i samma tråd, med ämnet
    som första mejlet faktiskt fick (`thread_subject`) när det finns.
    """
    from dataclasses import replace

    ctx = replace(ctx, step=step)
    body = _BODIES[step](ctx) + "\n\n-- \n" + _footer(ctx)
    title = thread_subject or subject(ctx)
    return (title if step == 1 else f"Re: {title}"), body


# --- Läsbarhet --------------------------------------------------------------
#
# Många som äger ett taxibolag har svenska som andraspråk. Vi vet inte vilka,
# och ska inte gissa på namnet -- så alla får samma lätta svenska: korta
# meningar, vanliga ord, inga talesätt. LIX mäter just det (meningslängd och
# andelen långa ord), och testerna håller varje mejl under gränsen.

LIX_MAX = 25            # under 25 är nivån i barnböcker; dagstidningar ligger runt 40
SENTENCE_MAX_WORDS = 14

_WORD = re.compile(r"[A-Za-zÅÄÖåäöé]+")


def prose(body: str) -> str:
    """Brödtexten: utan sidfot, signatur, länkar och citatet ur appen."""
    main = (body or "").partition("\n-- \n")[0].partition("Vänliga hälsningar")[0]
    main = re.sub(r"https?://\S+", "", main)
    return "\n".join(
        line for line in main.split("\n") if not line.strip().startswith('"')
    ).strip()


def sentences(text: str) -> list[list[str]]:
    parts = re.split(r"(?<=[.!?:])\s+|\n+", text)
    return [words for words in (_WORD.findall(part) for part in parts) if words]


def lix(text: str) -> int:
    """Läsbarhetsindex: ord per mening + andel ord längre än sex bokstäver."""
    rows = sentences(text)
    words = [word for row in rows for word in row]
    if not words:
        return 0
    long_words = sum(1 for word in words if len(word) > 6)
    return round(len(words) / len(rows) + 100 * long_words / len(words))


def longest_sentence(text: str) -> int:
    return max((len(row) for row in sentences(text)), default=0)


def lix_label(value: int) -> str:
    if value < 30:
        return "mycket lättläst"
    if value < 40:
        return "lättläst"
    return "för svår"


# --- HTML -----------------------------------------------------------------
#
# Så som ett mejl man skriver själv ser ut i Gmail eller Outlook: vanlig text,
# en länk i texten, en signatur på tre rader. Ingen knapp, ingen färgad ram,
# ingen bild -- det är det som får ett säljmejl att se ut som ytterligare ett
# utskick, och filtren läser det likadant. Texten är densamma som i textversionen.

_URL = re.compile(r"https?://[^\s<>\"]+")
_FONT = "Arial,Helvetica,sans-serif"
_INK = "#222222"
_MUTED = "#777777"
_LINE = "#dddddd"
_P = f"margin:0 0 14px 0;font-family:{_FONT};font-size:15px;line-height:1.5;color:{_INK}"


def _linkify(escaped: str) -> str:
    # Länken visas utan https:// och utan frågesträng: "taxitips.se/appen"
    # läses som en adress, en rad med utm-parametrar läses som reklam.
    def link(match: re.Match) -> str:
        url = match.group(0)
        shown = re.sub(r"^https?://", "", url).split("?", 1)[0].rstrip("/")
        return f'<a href="{url}">{shown}</a>'

    return _URL.sub(link, escaped)


def _lines(lines: list[str]) -> str:
    return "<br>".join(_linkify(html.escape(line)) for line in lines)


def _quote(text: str) -> str:
    return (
        f'<p style="{_P};margin-left:2px;padding-left:10px;border-left:2px solid {_LINE};'
        f'color:#444444">{html.escape(text)}</p>'
    )


def html_from_text(body: str) -> str:
    """
    Samma text som enkel HTML: stycken, länken som en vanlig länk, tipset i
    citattecken som ett citat och sidfoten (efter "-- ") liten och grå.
    """
    main, _, footer = (body or "").replace("\r\n", "\n").partition("\n-- \n")
    blocks: list[str] = []
    for raw in re.split(r"\n\s*\n", main.strip()):
        lines = [line.strip() for line in raw.split("\n") if line.strip()]
        if not lines:
            continue
        if len(lines) == 1 and lines[0].startswith('"') and lines[0].endswith('"') and len(lines[0]) > 2:
            blocks.append(_quote(lines[0][1:-1]))
        else:
            blocks.append(f'<p style="{_P}">{_lines(lines)}</p>')
    content = "\n".join(blocks)
    if footer.strip():
        small = f"margin:0 0 4px 0;font-family:{_FONT};font-size:12px;line-height:1.4;color:{_MUTED}"
        parts = "".join(
            f'<p style="{small}">{_linkify(html.escape(line))}</p>'
            for line in footer.strip().split("\n") if line.strip()
        )
        content += f'\n<div style="margin-top:24px">{parts}</div>'
    return (
        '<!doctype html><html lang="sv"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="margin:0;padding:0">'
        f'<div style="max-width:600px;padding:4px">\n{content}\n</div></body></html>'
    )
