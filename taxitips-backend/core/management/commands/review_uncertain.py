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
- thresholds.AI_MODEL_EXTRACT (låst Flash-Lite): billigast som räcker för
  klassificering. Anropet går via core/ai_client.py: kostnadslogg, dagstak,
  månadsbudget och TAXITIPS_AI=off.
- temperature=0: samma text → samma svar, cachen blir meningsfull.
- --limit: tak per körning.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from pydantic import BaseModel, Field

from core import ai_client, thresholds
from core.genkit import review
from core.models import Opportunity
from core.tip_facts import TipFacts


class ReviewVerdict(BaseModel):
    """Den äldre vägen, där modellen föreslog poängen själv. Granskningen läser
    numera fakta (core/tip_facts.TipFacts); schemat finns kvar för den äldre vägen."""

    score: int = Field(ge=0, le=100)
    severity_tier: str = ""
    stranded: bool = False
    has_alternative: bool | None = None
    mode: str | None = None
    from_station: str | None = None
    to_station: str | None = None
    why: str = Field(default="", max_length=300)


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
        from django.db.models import Q

        now = timezone.now()
        qs = (
            Opportunity.objects.filter(kind="transit", end_time__gt=now)
            .filter(Q(start_time__lte=now) | Q(start_time__isnull=True))
            .exclude(severity_tier="ignore")
        )
        if not options["all"]:
            qs = qs.filter(confidence="low")
        # Negativ cache: ett tips vars anrop nyss misslyckades väntar ut sin
        # backoff (ai_client.retry_allowed) i stället för att ta en plats i
        # varje körning. Ett misslyckat anrop lämnar `confidence=low` orört,
        # och utan det här valdes samma tips om var femte minut hela dygnet.
        ranked = list(qs.order_by("-demand_score")[: options["limit"] * 3])
        allowed = ai_client.retry_allowed("extract", [o.external_id for o in ranked], now)
        uncertain = [o for o in ranked if o.external_id in allowed][: options["limit"]]

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

        blocked = ai_client.unavailable_reason()
        if blocked:
            self.stdout.write(f"AI används inte just nu: {blocked}. Regelsvaren gäller.")
            return

        changed = failed = 0
        for o in uncertain:
            before_score = o.demand_score
            before_tier = o.severity_tier
            reclassify = o.confidence == "low"
            result = review(
                o,
                ai_client.json_caller(
                    "extract", TipFacts, model=thresholds.AI_MODEL_EXTRACT, subject=o.external_id,
                ),
                facts=True,
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
