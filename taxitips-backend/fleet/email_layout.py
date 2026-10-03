"""
Mejlens utseende: logga, färger, knapp och kodruta -- på ett ställe.

Två användare:

* **Utkorgen** (fleet/mailer.py) skickar varje rad som text OCH HTML. Texten
  är den som skrivs i fleet/notifications.py; HTML-versionen byggs här ur
  samma text, så att innehållet bara finns på ett ställe. `payload["button"]`
  (`{"url", "label"}`) blir en knapp, och raden i texten som bara är samma
  länk tas bort ur HTML-versionen (knappen ersätter den). `payload["code"]`
  blir en kodruta.
* **Supabase Auth** (GoTrue) hämtar sina mallar som filer från
  taxitips.se/email/ -- de genereras härifrån med
  `manage.py build_auth_email_templates`, med GoTrues platshållare
  (`{{ .Token }}`, `{{ .ConfirmationURL }}`) insatta orörda.

**Mejlklienter är inte webbläsare.** Tabeller, inline-stil, inga webbtypsnitt
som måste laddas, ingen SVG (Gmail visar den inte) och ingen mörk bakgrund på
hela mejlet -- en klient som vänder färgerna gör annars texten oläslig.
Loggan är en PNG med vit text på ett midnattsblått band, som ser likadan ut i
ljust och mörkt läge.
"""

from __future__ import annotations

import html
import re

from django.conf import settings

MIDNATT = "#14213d"
GULD = "#fca311"
LJUSGRA = "#f5f7fa"
SKIFFER = "#526078"
LINE = "#e3e7ee"

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO = "'SF Mono',Menlo,Consolas,'Courier New',monospace"

_URL = re.compile(r"https?://[^\s<>\"]+")


def site_url() -> str:
    return (getattr(settings, "FLEET_PUBLIC_SITE_URL", "") or "https://taxitips.se").rstrip("/")


def logo_url() -> str:
    return f"{site_url()}/email/logo.png"


def button(url: str, label: str) -> str:
    """En knapp som fungerar i Outlook: en tabellcell med bakgrund, inte bara en länk."""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:8px 0 20px">'
        f'<tr><td style="border-radius:999px;background:{GULD}">'
        f'<a href="{url}" style="display:inline-block;padding:14px 28px;font-family:{FONT};'
        f'font-size:16px;font-weight:700;color:{MIDNATT};text-decoration:none;border-radius:999px">'
        f"{label}</a></td></tr></table>"
    )


def code_box(code: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:8px 0 20px">'
        f'<tr><td style="background:{LJUSGRA};border:2px solid {GULD};border-radius:12px;'
        f'padding:14px 22px;font-family:{MONO};font-size:30px;font-weight:700;letter-spacing:6px;'
        f'color:{MIDNATT}">{code}</td></tr></table>'
    )


def paragraph(inner: str, *, muted: bool = False, small: bool = False) -> str:
    color = SKIFFER if muted else MIDNATT
    size = "13px" if small else "16px"
    return (
        f'<p style="margin:0 0 16px;font-family:{FONT};font-size:{size};line-height:1.55;'
        f'color:{color}">{inner}</p>'
    )


def heading(text: str) -> str:
    return (
        f'<h1 style="margin:0 0 16px;font-family:{FONT};font-size:22px;line-height:1.3;'
        f'font-weight:800;color:{MIDNATT}">{text}</h1>'
    )


def page(*, title: str, preheader: str, content: str, footer: str = "") -> str:
    """Hela mejlet. `content` och `footer` är färdig HTML."""
    footer = footer or (
        "Frågor? Svara på det här mejlet eller chatta med oss i appen."
        f'<br><a href="{site_url()}" style="color:{SKIFFER}">taxitips.se</a>'
    )
    return f"""<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{title}</title>
</head>
<body style="margin:0;padding:0;background:{LJUSGRA}">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{preheader}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{LJUSGRA}">
<tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px">
<tr><td style="background:{MIDNATT};border-radius:14px 14px 0 0;padding:22px 28px">
<img src="{logo_url()}" width="160" alt="Taxi Tips" style="display:block;border:0;width:160px;height:auto">
</td></tr>
<tr><td style="background:#ffffff;border:1px solid {LINE};border-top:0;border-radius:0 0 14px 14px;padding:28px">
{content}
</td></tr>
<tr><td style="padding:18px 28px;font-family:{FONT};font-size:12px;line-height:1.5;color:{SKIFFER};text-align:center">
{footer}
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def _linkify(escaped: str) -> str:
    return _URL.sub(
        lambda m: f'<a href="{m.group(0)}" style="color:{MIDNATT};font-weight:600">{m.group(0)}</a>',
        escaped,
    )


def from_text(subject: str, body: str, payload: dict | None = None) -> str:
    """
    HTML-versionen av ett utkorgsmejl, byggd ur dess text.

    Stycken skiljs av tomma rader. Avslutningen ("Hälsningar\\nTaxiTips") och
    allt efter den blir sidfot i stället för brödtext.
    """
    payload = payload or {}
    btn = payload.get("button") or {}
    btn_url = str(btn.get("url") or "").strip()
    code = str(payload.get("code") or "").strip()

    text = (body or "").replace("\r\n", "\n").strip()
    # Signaturen (notifications._SIGNATURE) är sidfot, inte innehåll.
    cut = text.find("\nFrågor? Svara på det här mejlet")
    if cut >= 0:
        text = text[:cut].strip()

    blocks = []
    placed = False
    for raw in re.split(r"\n\s*\n", text):
        lines = [ln for ln in raw.split("\n") if ln.strip()]
        if btn_url and any(ln.strip() == btn_url for ln in lines):
            # Länken blir en knapp; texten före den på samma stycke behålls.
            rest = [ln for ln in lines if ln.strip() != btn_url]
            if rest:
                blocks.append(paragraph("<br>".join(_linkify(html.escape(ln)) for ln in rest)))
            blocks.append(button(html.escape(btn_url, quote=True), html.escape(btn.get("label") or "Öppna")))
            placed = True
            continue
        if not lines:
            continue
        blocks.append(paragraph("<br>".join(_linkify(html.escape(ln)) for ln in lines)))
    if btn_url and not placed:
        blocks.append(button(html.escape(btn_url, quote=True), html.escape(btn.get("label") or "Öppna")))
    if code:
        blocks.insert(1 if blocks else 0, code_box(html.escape(code)))
    return page(
        title=html.escape(subject),
        preheader=html.escape(payload.get("preheader") or subject),
        content=heading(html.escape(subject)) + "\n".join(blocks),
    )
