"""
Låter en språkmodell granska osäkra bedömningar.

Körs bara på confidence=low -- resten är redan välgrundat, och att
granska det vore att betala för att bekräfta något systemet redan vet.

    python manage.py review_uncertain --dry-run   # visa vad som skulle granskas
    python manage.py review_uncertain             # kör på riktigt

Kostnadsval, medvetna
----------------------
- gemini-flash-lite-latest: den billigaste, snabbaste modellen som räcker
  för en enkel klassificeringsuppgift (poäng + boolean + kort motivering).
  Ingen anledning att betala för en tyngre modells resonemang här -- se
  docs/data-sources.md om du vill jämföra prisnivåer.
- temperature=0: samma text ska ge samma svar. Utan det blir cachen i
  core/genkit.py meningslös och poängen hoppar mellan cykler.
- --limit 40 (redan existerande golv): körs bara på de mest osäkra tipsen,
  inte alla. Kombinerat med confidence=low-filtret och cachen ovan är
  volymen per körning i praktiken någon handfull unika anrop.
"""

import asyncio
import os

from django.core.management.base import BaseCommand
from django.utils import timezone
from pydantic import BaseModel, Field

from core.genkit import review
from core.models import Opportunity

MODEL = "googleai/gemini-flash-lite-latest"

# Genkit-instansen mintas lazy, bara när ett riktigt anrop faktiskt görs --
# --dry-run ska aldrig kräva en nyckel, precis som innan.
_ai = None


def _genkit():
    global _ai
    if _ai is not None:
        return _ai
    from genkit import Genkit
    from genkit_google_genai import GoogleAI

    # GoogleAI (Gemini Developer API-nyckel) -- inte VertexAI. Projektet
    # "taxibehov" har fakturering avstängd; VertexAI kräver ett GCP-konto
    # med fakturering aktiverad, GoogleAI gör det inte (samma fria nivå
    # som redan användes via rå HTTP innan den här ändringen).
    _ai = Genkit(plugins=[GoogleAI()], model=MODEL)
    return _ai


class ReviewVerdict(BaseModel):
    """Samma form som core/genkit.py:s PROMPT redan ber om -- Genkits
    schemavalidering ersätter den gamla regex-baserade JSON-utplockningen,
    utan att ändra vad review() förväntar sig få tillbaka."""

    score: int = Field(ge=0, le=100)
    stranded: bool = False
    why: str = Field(default="", max_length=300)


def call_genkit(prompt: str) -> str:
    """
    Anropar Gemini via Genkit. Nyckeln tas från GEMINI_API_KEY (samma
    miljövariabel som innan).

    Returnerar en JSON-sträng, inte det validerade objektet direkt --
    core/genkit.py:s review()/_parse() förblir orörda, och deras redan
    testade "JSON inbäddat i prosa"-fall gäller fortfarande om Genkits
    egen schemavalidering någon gång inte slår till.
    """
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY saknas. Skapa en nyckel på "
            "https://aistudio.google.com/apikey och lägg i .env"
        )
    ai = _genkit()

    async def _run() -> str:
        response = await ai.generate(
            model=MODEL,
            prompt=prompt,
            output_schema=ReviewVerdict,
            config={"temperature": 0},
        )
        return response.output.model_dump_json()

    return asyncio.run(_run())


class Command(BaseCommand):
    help = "Granskar osäkra tips med en språkmodell (sänker aldrig fel håll)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=40)

    def handle(self, *args, **options):
        uncertain = list(
            Opportunity.objects.filter(
                confidence="low", end_time__gt=timezone.now()
            ).exclude(severity_tier="ignore").order_by("-demand_score")[: options["limit"]]
        )

        if not uncertain:
            self.stdout.write(
                "inga osäkra tips just nu -- regelverket räcker.\n"
                "Modellen körs bara på confidence=low; efter tågsignalerna "
                "ligger alla tågtips på high."
            )
            return

        if options["dry_run"]:
            for o in uncertain:
                self.stdout.write(f"  {o.demand_score:3}  {(o.title or '')[:64]}")
            self.stdout.write(f"\n{len(uncertain)} tips skulle granskas (inget anropades)")
            return

        lowered = failed = 0
        for o in uncertain:
            before = o.demand_score
            result = review(o, call_genkit)
            if result is None:
                failed += 1
                continue
            if result.final_score < before:
                lowered += 1
                self.stdout.write(
                    f"  {before} → {result.final_score}  {(o.title or '')[:50]}"
                )

        self.stdout.write(self.style.SUCCESS(
            f"granskade {len(uncertain)}, sänkte {lowered}, misslyckades {failed}"
        ))
