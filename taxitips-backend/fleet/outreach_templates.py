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
    return f"{site()}{APP_PATH}?utm_source=mejl&utm_campaign={ctx.campaign}"


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
    if ctx.size == SOLO:
        return "Var står du när alla behöver taxi?"
    return "Var står era bilar när alla behöver taxi?"


def _offer(ctx: Context) -> str:
    you = "Du" if ctx.size == SOLO else "Ni"
    return (
        f"Det kostar inget i en månad. {you} behöver inget kort. "
        f"{you} börjar i appen:\n{app_url(ctx)}"
    )


# Tre öppningsbilder, en per mottagare. Hundra likadana mejl om dagen ser ut som
# ett massutskick för ett skräppostfilter; tre varianter gör det inte, och
# ingen av dem är mindre sann än de andra.
_SCENES = (
    "Ett tåg ställs in en kväll. Många står på stationen och vill hem.",
    "Sista planet landar sent en kväll. Inga bussar går. Alla vill hem.",
    "En konsert slutar klockan tio. Alla går ut på gatan samtidigt.",
)


def _step1(ctx: Context) -> str:
    scene = _SCENES[ctx.variant % len(_SCENES)]
    if ctx.size == SOLO:
        middle = [
            "De flesta förare får veta det för sent. Du kan få veta det direkt.",
            "Appen Taxi Tips säger till när många behöver taxi. Du ser var och "
            "varför. Då står du där kunderna är.",
            f"Vill du prova med din bil{_where(ctx)}? " + _offer(ctx),
        ]
    elif ctx.size == LARGE:
        middle = [
            "Ni har många bilar ute samtidigt. Hur många står på rätt plats just då?",
            "Appen Taxi Tips säger till era förare när många behöver taxi. De ser "
            "var och varför.",
            f"Vill ni på {ctx.company} se det? Svara på mejlet, så visar jag det "
            "på tio minuter. Eller prova med en bil. " + _offer(ctx),
        ]
    else:
        middle = [
            "De flesta förare får veta det för sent. Era kan få veta det direkt.",
            "Appen Taxi Tips säger till föraren när många behöver taxi. Föraren ser "
            "var och varför. Då står bilen där kunderna är.",
            f"Vill ni på {ctx.company} prova med en bil{_where(ctx)}? " + _offer(ctx),
        ]
    return "\n\n".join([_greeting(ctx), scene, *middle, "Vänliga hälsningar\n" + _signature()])


def _step2(ctx: Context) -> str:
    if ctx.size == SOLO:
        phone, ask = "din telefon", f"Vill du prova med din bil{_where(ctx)}? " + _offer(ctx)
    elif ctx.size == LARGE:
        phone = "förarens telefon"
        ask = (
            "Ska jag visa det på tio minuter? Svara på mejlet. Ni kan också prova "
            "med en bil. " + _offer(ctx)
        )
    else:
        phone, ask = "förarens telefon", f"Vill ni prova med en bil{_where(ctx)}? " + _offer(ctx)
    return "\n\n".join([
        _greeting(ctx, again=True),
        f"Så här ser ett tips ut i {phone}:",
        "\"Avgången 18:42 från Uppsala C är inställd. Nästa avgång 19:30.\"",
        "Den som ser det först kommer dit först.",
        ask,
        "Vänliga hälsningar\n" + _signature(),
    ])


def _step3(ctx: Context) -> str:
    if ctx.size == SOLO:
        helps, start = "hjälper dig att hitta rätt", "Du kan börja när du vill"
    else:
        helps, start = "hjälper era förare att hitta rätt", "Ni kan börja när ni vill"
    return "\n\n".join([
        _greeting(ctx),
        "Det här är mitt sista mejl.",
        f"En förare vet inte var nästa kund står. Taxi Tips {helps}.",
        "Vill du hellre prata? Svara med ditt telefonnummer, så ringer jag.",
        f"{start}. Hämta appen här:\n{app_url(ctx)}",
        "Vänliga hälsningar\n" + _signature(),
    ])


_BODIES = {1: _step1, 2: _step2, 3: _step3}


def render(step: int, ctx: Context) -> tuple[str, str]:
    """(ämne, text) för steg 1-3. Uppföljningarna svarar i samma tråd."""
    body = _BODIES[step](ctx) + "\n\n-- \n" + _footer(ctx)
    title = subject(ctx)
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
# Ren och lätt, utan bilder. En logga eller en banderoll hade sett proffsigare
# ut i en skärmdump, men mejlklienter blockerar bilder från okända avsändare
# och filtren läser bildtunga mejl som reklam. Formen bärs i stället av
# typografin: luft, en tydlig knapp, ett tipskort och en signatur med kant i
# varumärkets färg. Texten är densamma som i textversionen.

_URL = re.compile(r"https?://[^\s<>\"]+")
_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_INK = "#1f2937"
_MUTED = "#6b7280"
_MIDNATT = "#14213d"
_GULD = "#fca311"
_LINE = "#e3e7ee"
_PANEL = "#f5f7fa"
BUTTON_LABEL = "Hämta appen"
_P = f"margin:0 0 16px 0;font-family:{_FONT};font-size:16px;line-height:1.6;color:{_INK}"


def _linkify(escaped: str) -> str:
    # Länken visas utan https:// och utan frågesträng: "taxitips.se/appen"
    # läses som en adress, en rad med utm-parametrar läses som reklam.
    def link(match: re.Match) -> str:
        url = match.group(0)
        shown = re.sub(r"^https?://", "", url).split("?", 1)[0].rstrip("/")
        return f'<a href="{url}" style="color:{_MIDNATT}">{shown}</a>'

    return _URL.sub(link, escaped)


def _lines(lines: list[str]) -> str:
    return "<br>".join(_linkify(html.escape(line)) for line in lines)


def _button(url: str) -> str:
    """Tabell runt länken: Outlook ritar annars ingen bakgrund bakom texten."""
    href = html.escape(url, quote=True)
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:0 0 20px 0"><tr>'
        f'<td bgcolor="{_MIDNATT}" style="background:{_MIDNATT};border-radius:8px">'
        f'<a href="{href}" style="display:inline-block;padding:12px 22px;font-family:{_FONT};'
        'font-size:16px;font-weight:600;line-height:1.2;color:#ffffff;text-decoration:none">'
        f"{BUTTON_LABEL}</a></td></tr></table>"
    )


def _tip_card(text: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
        'style="margin:0 0 16px 0"><tr>'
        f'<td style="background:{_PANEL};border-left:3px solid {_GULD};border-radius:0 10px 10px 0;'
        f'padding:14px 16px;font-family:{_FONT};font-size:16px;line-height:1.5;color:{_INK}">'
        f'<span style="display:block;margin-bottom:4px;font-size:12px;font-weight:600;'
        f'letter-spacing:0.04em;text-transform:uppercase;color:{_MUTED}">Tips i appen</span>'
        f"{html.escape(text)}</td></tr></table>"
    )


def _signature_block(lines: list[str]) -> str:
    name, rest = (lines[0], lines[1:]) if lines else ("", [])
    detail = "<br>".join(html.escape(line) for line in rest)
    return (
        f'<p style="{_P};margin-bottom:10px">Vänliga hälsningar</p>'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td style="border-left:3px solid {_GULD};padding:2px 0 2px 12px;font-family:{_FONT};'
        f'font-size:15px;line-height:1.5;color:{_INK}">'
        f'<strong style="font-weight:600">{html.escape(name)}</strong>'
        + (f'<br><span style="color:{_MUTED}">{detail}</span>' if detail else "")
        + "</td></tr></table>"
    )


def html_from_text(body: str) -> str:
    """
    Samma text som HTML. Raden som bara är länken till appen blir en knapp,
    tipset i citattecken ett kort, signaturen får en kant och sidfoten (efter
    "-- ") blir liten och grå under en linje.
    """
    main, _, footer = (body or "").replace("\r\n", "\n").partition("\n-- \n")
    blocks: list[str] = []
    for raw in re.split(r"\n\s*\n", main.strip()):
        lines = [line for line in raw.split("\n") if line.strip()]
        if not lines:
            continue
        last = lines[-1].strip()
        if lines[0].strip() == "Vänliga hälsningar":
            blocks.append(_signature_block([line.strip() for line in lines[1:]]))
        elif _URL.fullmatch(last) and APP_PATH in last:
            if lines[:-1]:
                blocks.append(f'<p style="{_P};margin-bottom:12px">{_lines(lines[:-1])}</p>')
            blocks.append(_button(last))
        elif len(lines) == 1 and last.startswith('"') and last.endswith('"') and len(last) > 2:
            blocks.append(_tip_card(last[1:-1]))
        else:
            blocks.append(f'<p style="{_P}">{_lines(lines)}</p>')
    content = "\n".join(blocks)
    if footer.strip():
        small = (
            f"margin:0 0 6px 0;font-family:{_FONT};font-size:12px;line-height:1.5;color:{_MUTED}"
        )
        parts = "".join(
            f'<p style="{small}">{_linkify(html.escape(line))}</p>'
            for line in footer.strip().split("\n") if line.strip()
        )
        content += (
            f'\n<div style="margin-top:28px;padding-top:14px;border-top:1px solid {_LINE}">'
            f"{parts}</div>"
        )
    return (
        '<!doctype html><html lang="sv"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light"></head>'
        '<body style="margin:0;padding:0;background:#ffffff">'
        f'<div style="max-width:560px;padding:8px 4px">\n{content}\n</div></body></html>'
    )
