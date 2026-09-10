"""
Låter en språkmodell granska osäkra bedömningar.

Körs på confidence=low (omklassning med full kontext). Med --all även
övriga aktiva tipps utan ignore -- då bara som dämpning om confidence
inte är low.

    python manage.py review_uncertain --dry-run
    python manage.py review_uncertain
    python manage.py review_uncertain --force --limit 40
    python manage.py review_uncertain --all --force

Kostnadsval, medvetna
----------------------
- gemini-flash-lite-latest: billigast som räcker för klassificering.
- temperature=0: samma text → samma svar, cachen blir meningsfull.
- --limit: tak per körning.
"""

import asyncio
import os

from django.core.management.base import BaseCommand
from django.utils import timezone
from pydantic import BaseModel, Field

from core.genkit import review
from core.models import Opportunity

MODEL = "googleai/gemini-flash-lite-latest"

_ai = None


def _genkit():
    global _ai
    if _ai is not None:
        return _ai
    from genkit import Genkit
    from genkit_google_genai import GoogleAI

    _ai = Genkit(plugins=[GoogleAI()], model=MODEL)
    return _ai


class ReviewVerdict(BaseModel):
    score: int = Field(ge=0, le=100)
    severity_tier: str = ""
    stranded: bool = False
    has_alternative: bool | None = None
    why: str = Field(default="", max_length=300)


def call_genkit(prompt: str) -> str:
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
    help = (
        "Omklassar osäkra tips med Genkit (full kontext). "
        "confidence=low får höjas/sänkas; övriga bara sänkas."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=40)
        parser.add_argument(
            "--force",
            action="store_true",
            help="Hoppa över cache och anropa modellen igen.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Alla aktiva tipps (inte bara confidence=low).",
        )

    def handle(self, *args, **options):
        qs = (
            Opportunity.objects.filter(end_time__gt=timezone.now())
            .exclude(severity_tier="ignore")
            .exclude(kind="road")
        )
        if not options["all"]:
            qs = qs.filter(confidence="low")
        uncertain = list(qs.order_by("-demand_score")[: options["limit"]])

        if not uncertain:
            self.stdout.write(
                "inga tips att granska just nu "
                "(confidence=low tomt; prova --all).\n"
            )
            return

        if options["dry_run"]:
            for o in uncertain:
                self.stdout.write(
                    f"  {o.demand_score:3}  {o.confidence:6}  "
                    f"{o.severity_tier or '?':22}  {(o.title or '')[:56]}"
                )
            self.stdout.write(
                f"\n{len(uncertain)} tips skulle granskas (inget anropades)"
            )
            return

        changed = failed = 0
        for o in uncertain:
            before_score = o.demand_score
            before_tier = o.severity_tier
            reclassify = o.confidence == "low"
            result = review(
                o,
                call_genkit,
                reclassify=reclassify,
                bypass_cache=options["force"],
            )
            if result is None:
                failed += 1
                continue
            o.refresh_from_db()
            if o.demand_score != before_score or o.severity_tier != before_tier:
                changed += 1
                self.stdout.write(
                    f"  {before_score}/{before_tier} → "
                    f"{o.demand_score}/{o.severity_tier}  "
                    f"{(o.title or '')[:48]}"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"granskade {len(uncertain)}, ändrade {changed}, "
                f"misslyckades {failed}"
            )
        )
