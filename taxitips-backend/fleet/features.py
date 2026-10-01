"""
Vad ett företag får SE: provet visar bara tåg och buss, betalningen öppnar resten.

**Varför provet är smalt.** Provet ska ge en smak av appen -- nog för att
föraren ser att tipsen stämmer -- men inte hela produkten gratis i sju
dagar. Tåg & buss är kärnan (inställda tåg, sista avgången) och det som
säljer; väg, flyg, färjor och evenemang syns som låsta kategorier med antal,
så att föraren ser vad som finns bakom.

**Vad som öppnar allt.** En betald period i vilken form som helst: ett
abonnemang, betalningsfristen, en kupongs gratisdagar, och ett prov där
kunden redan beställt och sparat kort (`commerce.has_active_trial_commit`) --
den kunden har betalat, bara inte dragits än. Allt som INTE är ett pågående
prov räknas som betalt här; åtkomsten i övrigt (period, licens, län) prövas
fortfarande av fleet/access.py, den här modulen smalnar bara av.

**Var låset sitter.** På servern, i varje väg som lämnar ut data: flödet,
detaljvyn, favoriterna, färjorna, evenemangen och notiserna
(fleet/push_gate.py). Appen visar låset, men att dölja något i appen skyddar
ingenting.

**Ingen betalning i appen.** Svaret på ett lås är en text, aldrig en länk
eller ett pris: köpet sker i kundportalen på webben, genom mejlet eller med
en säljare (docs/fleet-abonnemang.md §9c).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.utils import timezone

# Samma kategorier som kartans kategorirad (lib/signal_kinds.dart) och
# notisinställningarna (core/notify.CATEGORY_CATALOG), plus evenemangen, som
# har en egen vy och inte är tips.
ALL_CATEGORIES = ("transit", "road", "flight", "ferry", "events")
TRIAL_CATEGORIES = ("transit",)

LOCKED_REASON = "feature_locked"
LOCKED_MESSAGE = (
    "Ingår när företaget har ett abonnemang. Under provet visas tåg och buss."
)


@dataclass(frozen=True)
class Features:
    categories: tuple[str, ...]
    plan: str  # "full" | "trial"

    @property
    def full(self) -> bool:
        return self.plan == "full"

    @property
    def locked(self) -> tuple[str, ...]:
        return tuple(c for c in ALL_CATEGORIES if c not in self.categories)

    def allows(self, category: str) -> bool:
        return category in self.categories

    def as_dict(self) -> dict:
        return {
            "plan": self.plan,
            "categories": list(self.categories),
            "locked": list(self.locked),
            "lockedMessage": LOCKED_MESSAGE if self.locked else "",
        }


FULL = Features(ALL_CATEGORIES, "full")
TRIAL = Features(TRIAL_CATEGORIES, "trial")


def of(ent) -> Features:
    """Planen på en åtkomst; FULL när den saknas (äldre vägar och testernas attrapper)."""
    return getattr(ent, "features", None) or FULL


def for_company(company_id, now=None) -> Features:
    """
    Kategorierna för företaget just nu. Frågar inte om perioden är giltig --
    det gör fleet/access.py -- bara om den är ett okommitterat prov.
    """
    if not company_id:
        return FULL
    from fleet import commerce
    from fleet.access import company_window

    now = now or timezone.now()
    window = company_window(company_id, now)
    if window.reason != "trial":
        return FULL
    if commerce.has_active_trial_commit(company_id):
        return FULL
    from fleet.models import Trial

    # En kupong är ett beslut av plattformsadministratören att ge gratisdagar
    # (fleet/sales.py), inte ett prov: den öppnar allt.
    source = (
        Trial.objects.filter(company_id=company_id, status=Trial.Status.ACTIVE)
        .order_by("-created_at").values_list("source", flat=True).first()
    )
    if source == Trial.Source.COUPON:
        return FULL
    return TRIAL


def category_of_row(row: dict) -> str:
    """`core.notify.category_of` för ett serialiserat tips eller en ögonblicksbild."""
    kind = (row or {}).get("kind")
    if kind in ("road", "flight", "ferry"):
        return kind
    mode = (row or {}).get("mode")
    if mode in ("road", "flight"):
        return mode
    return "transit"


def filter_rows(features: Features, rows: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Raderna som får visas, och antalet dolda per kategori (för låsraden i appen)."""
    if features.full:
        return rows, {}
    kept: list[dict] = []
    hidden: dict[str, int] = {}
    for row in rows:
        category = category_of_row(row)
        if features.allows(category):
            kept.append(row)
        else:
            hidden[category] = hidden.get(category, 0) + 1
    return kept, hidden
