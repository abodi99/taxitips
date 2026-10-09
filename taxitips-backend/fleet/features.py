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

**Ett manuellt beviljande väljer själv.** En plattformsadministratör kan
bevilja ett medlemskap utan kostnad med bara vissa kategorier
(fleet/grants.py, `MembershipGrant.categories`). Då är planen `grant` och
kategorierna unionen över bolagets aktiva beviljanden. Ett beviljande smalnar
aldrig av ett bolag som ändå betalar: perioden bakom beviljandet prövas, och
är den betald gäller FULL.

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
# Visas i appen: neutral, utan pris eller väg till köp (App Store 3.1.1,
# Google Play Payments). Samma ord som appens lib/membership_copy.dart.
LOCKED_MESSAGE = (
    "Ingår inte i provet. Ditt företags administratör hanterar medlemskapet på webben."
)
# Samma sak för ett beviljande med valda kategorier: det är inget prov.
GRANT_LOCKED_MESSAGE = (
    "Ingår inte i ditt medlemskap. Ditt företags administratör hanterar medlemskapet på webben."
)


@dataclass(frozen=True)
class Features:
    categories: tuple[str, ...]
    plan: str  # "full" | "trial" | "grant"

    @property
    def full(self) -> bool:
        # Kategorierna avgör, inte planens namn: filtret får aldrig hoppas över
        # för en plan som saknar en kategori, vad den än heter.
        return set(ALL_CATEGORIES) <= set(self.categories)

    @property
    def locked_message(self) -> str:
        if not self.locked:
            return ""
        return GRANT_LOCKED_MESSAGE if self.plan == "grant" else LOCKED_MESSAGE

    @property
    def cache_key(self) -> str:
        """Del av flödets ETag: två planer med olika kategorier får aldrig dela svar."""
        return self.plan if self.full else f"{self.plan}.{'.'.join(self.categories)}"

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
            "lockedMessage": self.locked_message,
        }


FULL = Features(ALL_CATEGORIES, "full")
TRIAL = Features(TRIAL_CATEGORIES, "trial")


def of(ent) -> Features:
    """Planen på en åtkomst; FULL när den saknas (äldre vägar och testernas attrapper)."""
    return getattr(ent, "features", None) or FULL


def for_company(company_id, now=None) -> Features:
    """
    Kategorierna för företaget just nu. Frågar inte om perioden är giltig --
    det gör fleet/access.py -- bara om den är ett okommitterat prov eller ett
    beviljande med valda kategorier.
    """
    if not company_id:
        return FULL
    from fleet import grants
    from fleet.access import company_window

    now = now or timezone.now()
    window = company_window(company_id, now)
    if window.reason == grants.WINDOW_REASON:
        return _for_grant(company_id, now)
    return _for_period(company_id, window.reason)


def _for_grant(company_id, now) -> Features:
    """
    Ett aktivt manuellt beviljande: unionen av de valda kategorierna.

    Beviljandet går före abonnemanget i `company_window`, men det får inte
    ta något ifrån ett bolag som ändå har en period: ett betalande bolag som
    ger en extra person "bara tåg och buss" ska inte tappa resten för alla
    sina förare. Perioden bakom beviljandet prövas därför, och dess
    kategorier läggs till (FULL för en betald period, tåg och buss för ett
    pågående prov).
    """
    from fleet import grants

    chosen = grants.granted_categories(company_id, now)
    if chosen is None or set(ALL_CATEGORIES) <= chosen:
        return FULL
    from fleet.access import _subscription_window

    underlying = _subscription_window(company_id, now)
    if underlying.ok:
        base = _for_period(company_id, underlying.reason)
        if base.full:
            return FULL
        chosen = chosen | set(base.categories)
    if set(ALL_CATEGORIES) <= chosen:
        return FULL
    return Features(tuple(c for c in ALL_CATEGORIES if c in chosen), "grant")


def _for_period(company_id, reason: str) -> Features:
    """Kategorierna för en period utan beviljande: allt utom ett okommitterat prov."""
    from fleet import commerce

    # Även ett prov som väntar på första telefonen: välkomsten i appen visar
    # då vad provet kommer att omfatta. Åtkomsten ger ändå inga tips förrän
    # provet startat (fleet/access.py), så det öppnar inget.
    if reason not in ("trial", "trial_not_started"):
        return FULL
    if commerce.has_active_trial_commit(company_id):
        return FULL
    from fleet.models import Trial

    # En kupong är ett beslut av plattformsadministratören att ge gratisdagar
    # (fleet/sales.py), inte ett prov: den öppnar allt.
    source = (
        Trial.objects.filter(
            company_id=company_id, status__in=[Trial.Status.ACTIVE, Trial.Status.PENDING]
        )
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
