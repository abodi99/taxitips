"""
Skriver Supabase Auths mejlmallar (GoTrue) till taxitips-web/public/email/.

    manage.py build_auth_email_templates
    manage.py build_auth_email_templates --out /annan/katalog

Mallarna publiceras med webben på https://taxitips.se/email/<namn>.html och
GoTrue hämtar dem via `GOTRUE_MAILER_TEMPLATES_<TYP>` (se docs/auth-mejl.md).
Utseendet kommer från fleet/email_layout.py, samma som utkorgens mejl, så att
ett registreringsmejl och en förarinbjudan ser ut att komma från samma ställe.

GoTrues platshållare (`{{ .Token }}`, `{{ .ConfirmationURL }}`) sätts in
orörda -- de är Go-mallar och fylls i av GoTrue, inte här.

**Kod och länk.** Appen ber om koden (verifyOTP), portalen och adminwebben
följer länken. Registrering och inloggning har därför båda; återställning
har bara länken, eftersom appen skickar den till sidan där lösenordet väljs.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from fleet import email_layout as L

TOKEN = "{{ .Token }}"
URL = "{{ .ConfirmationURL }}"

IGNORE = "Var det inte du? Då kan du strunta i det här mejlet – inget händer utan koden eller länken."

TEMPLATES = {
    # Registrering (signUp) och bekräftelse av e-post.
    "confirmation": dict(
        title="Bekräfta din e-post",
        preheader=f"Din kod: {TOKEN}",
        content=(
            L.heading("Bekräfta din e-post")
            + L.paragraph("Välkommen till Taxi Tips! Skriv den här koden i appen för att slutföra registreringen:")
            + L.code_box(TOKEN)
            + L.paragraph("Registrerade du dig på taxitips.se? Tryck på knappen i stället:")
            + L.button(URL, "Bekräfta e-post")
            + L.paragraph(IGNORE, muted=True, small=True)
        ),
    ),
    # Inloggning med kod eller länk (signInWithOtp).
    "magic_link": dict(
        title="Din inloggningskod",
        preheader=f"Din kod: {TOKEN}",
        content=(
            L.heading("Logga in på Taxi Tips")
            + L.paragraph("Skriv koden i appen:")
            + L.code_box(TOKEN)
            + L.paragraph("Eller tryck på knappen för att logga in direkt:")
            + L.button(URL, "Logga in")
            + L.paragraph("Koden och länken fungerar en gång. " + IGNORE, muted=True, small=True)
        ),
    ),
    "recovery": dict(
        title="Välj ett nytt lösenord",
        preheader="Tryck på knappen för att välja ett nytt lösenord.",
        content=(
            L.heading("Välj ett nytt lösenord")
            + L.paragraph("Någon bad om att få byta lösenordet för {{ .Email }}. Tryck på knappen och välj ett nytt:")
            + L.button(URL, "Välj nytt lösenord")
            + L.paragraph(
                "Länken fungerar en gång. Bad du inte om det här? Då kan du strunta i mejlet – "
                "lösenordet ändras inte.", muted=True, small=True,
            )
        ),
    ),
    # Används bara om något anropar GoTrues egen /invite. Våra inbjudningar
    # mejlas av utkorgen (fleet/notifications.py), som vet vem som bjöd in.
    "invite": dict(
        title="Du är inbjuden till Taxi Tips",
        preheader="Tryck på knappen för att komma igång.",
        content=(
            L.heading("Du är inbjuden till Taxi Tips")
            + L.paragraph("Tryck på knappen för att skapa ditt konto och välja ett lösenord:")
            + L.button(URL, "Kom igång")
            + L.paragraph("Väntade du dig inte det här mejlet kan du strunta i det.", muted=True, small=True)
        ),
    ),
    "email_change": dict(
        title="Bekräfta din nya e-post",
        preheader="Bekräfta bytet till {{ .NewEmail }}.",
        content=(
            L.heading("Bekräfta din nya e-post")
            + L.paragraph("Du vill byta inloggning från {{ .Email }} till {{ .NewEmail }}. Tryck på knappen för att bekräfta:")
            + L.button(URL, "Bekräfta bytet")
            + L.paragraph("Bad du inte om det här? Svara på mejlet så hjälper vi dig.", muted=True, small=True)
        ),
    ),
    "reauthentication": dict(
        title="Bekräfta att det är du",
        preheader=f"Din kod: {TOKEN}",
        content=(
            L.heading("Bekräfta att det är du")
            + L.paragraph("Skriv koden för att fortsätta:")
            + L.code_box(TOKEN)
            + L.paragraph(IGNORE, muted=True, small=True)
        ),
    ),
}

# Ämnesraderna sätts som miljövariabler i GoTrue (docs/auth-mejl.md).
SUBJECTS = {
    "confirmation": "Din kod till Taxi Tips",
    "magic_link": "Din inloggningskod till Taxi Tips",
    "recovery": "Välj ett nytt lösenord för Taxi Tips",
    "invite": "Du är inbjuden till Taxi Tips",
    "email_change": "Bekräfta din nya e-post för Taxi Tips",
    "reauthentication": "Din kod till Taxi Tips",
}


class Command(BaseCommand):
    help = "Skriver Supabase Auths mejlmallar till taxitips-web/public/email/."

    def add_arguments(self, parser):
        default = Path(settings.BASE_DIR).parent / "taxitips-web" / "public" / "email"
        parser.add_argument("--out", default=str(default))

    def handle(self, *args, out: str, **options):
        target = Path(out)
        target.mkdir(parents=True, exist_ok=True)
        for name, t in TEMPLATES.items():
            html = L.page(title=t["title"], preheader=t["preheader"], content=t["content"])
            (target / f"{name}.html").write_text(html, encoding="utf-8")
            self.stdout.write(f"{name}.html  ämne: {SUBJECTS[name]}")
        self.stdout.write(self.style.SUCCESS(f"Klart: {target}"))
