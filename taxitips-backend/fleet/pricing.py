"""
Prismotorn. Auktoritativ, på servern, i heltal ören.

Klienten räknar aldrig ut ett belopp. Den visar det den fick, och den order
kunden godkänner bär exakt de raderna -- annars går en faktura inte att
förklara i efterhand.

**Reglerna** (prisversion `2026-09-v1`, alla belopp exklusive moms):

* 1--9 köpta billicenser: 799 kr per bil och månad.
* Minst 10 köpta billicenser: 749 kr för SAMTLIGA köpta licenser, inte bara
  de över gränsen.
* Extra län: 199 kr per bil, extra län och månad. Rabatteras aldrig.
* Introduktion: 699 kr per bil och månad under företagets första tre
  sammanhängande betalmånader.

**"Introduktion och volymrabatt kombineras inte" -- hur det tolkas här.**
Texten säger att de inte får staplas, inte vilken som vinner. Motorn lägger
därför aldrig ihop dem utan tar den lägsta av (introduktionspris,
tiggarpriset för volymen): med dagens tal betyder det 699 kr, eftersom
introduktionen redan är lägre än volymrabatten. Tolkningen är den kund-
gynnande, och den är robust om priserna ändras: två rabatter kan aldrig bli
en tredje, djupare rabatt. Står avtalet fast vid motsatsen räcker det att
byta `_unit_price_ore` -- ingen annan kod känner till regeln.

**Proportionering.** Ett tillägg mitt i perioden kostar den återstående
delen av perioden, räknat på sekunder och avrundat till närmaste öre. Beloppet
"nu" är skillnaden mellan det nya och det gamla månadsbeloppet, proportionerat
-- inte priset på det tillagda ensamt. Det är enda sättet att få 9 -> 10 rätt:
den tionde bilen gör alla nio billigare, och kunden ska betala mellanskillnaden
(10 x 749 - 9 x 799 = 299 kr/mån), inte 749 kr.

**Moms.** `vat_rate_bp` på prisversionen, i hundradels procent (2500 = 25 %).
Det fanns ingen momshantering att återanvända i kodbasen -- bara strängen
"exkl. moms" i en vy -- så satsen är ett konfigurerat fält på prisversionen
och inte en konstant i koden.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from fleet.models import PriceVersion, Subscription


@dataclass(frozen=True)
class LineItem:
    """En rad i uträkningen kunden ser innan hen godkänner."""

    key: str
    label: str
    quantity: int
    unit_price_ore: int
    amount_ore: int
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Quote:
    currency: str
    vat_rate_bp: int
    amount_ore: int
    vat_ore: int
    total_ore: int
    lines: list[LineItem] = field(default_factory=list)
    price_version: str = ""

    def as_dict(self) -> dict:
        return {
            "currency": self.currency,
            "vatRateBp": self.vat_rate_bp,
            "amountOre": self.amount_ore,
            "vatOre": self.vat_ore,
            "totalOre": self.total_ore,
            "priceVersion": self.price_version,
            "lines": [line.as_dict() for line in self.lines],
        }


# ---------------------------------------------------------------------------
# Heltalsaritmetik
# ---------------------------------------------------------------------------


def _round_div(numerator: int, denominator: int) -> int:
    """
    Heltalsdivision med avrundning till närmaste, halvor uppåt.

    Egen funktion i stället för round(): Pythons round() är bankers rounding
    (round(0.5) == 0) och skulle ge ett ören fel åt olika håll beroende på
    beloppet. En faktura ska gå att räkna efter för hand.
    """
    if denominator == 0:
        return 0
    if numerator < 0:
        return -((-numerator * 2 + denominator) // (denominator * 2))
    return (numerator * 2 + denominator) // (denominator * 2)


def vat_of(amount_ore: int, vat_rate_bp: int) -> int:
    """Momsen på ett belopp. `vat_rate_bp` är hundradels procent: 2500 = 25 %."""
    return _round_div(amount_ore * vat_rate_bp, 10_000)


def proration_factor(now: datetime, period_start: datetime, period_end: datetime) -> tuple[int, int]:
    """
    (återstående sekunder, periodens sekunder). Båda heltal; kvoten används
    aldrig som float.

    Utanför perioden ger den 0/1 respektive hela perioden, så att en felaktig
    klocka aldrig kan ge ett negativt eller ett uppblåst belopp.
    """
    if not period_start or not period_end or period_end <= period_start:
        return (0, 1)
    total = int((period_end - period_start).total_seconds())
    remaining = int((period_end - now).total_seconds())
    remaining = max(0, min(remaining, total))
    return (remaining, total)


def prorate(amount_ore: int, remaining: int, total: int) -> int:
    return _round_div(amount_ore * remaining, total)


# ---------------------------------------------------------------------------
# Introduktionskampanjen
# ---------------------------------------------------------------------------


def intro_available(price: PriceVersion, first_paid_at: datetime | None) -> bool:
    """
    Får det här företaget alls börja på introduktionspris?

    Kräver att kampanjen är påslagen OCH att ett lanseringsdatum är satt.
    Utan datum är svaret nej -- ett gissat lanseringsdatum hade börjat ge
    rabatt till fel företag, och det syns först på fakturan.
    """
    if not price.intro_enabled or price.launch_date is None:
        return False
    if first_paid_at is None:
        return False
    launch: date = price.launch_date
    started: date = first_paid_at.date()
    if started < launch:
        return False
    return (started - launch).days <= price.intro_signup_window_days


def intro_window(price: PriceVersion, first_paid_at: datetime) -> datetime:
    """
    Slutet på introduktionen: tre sammanhängande betalmånader från första
    betalningen. Sammanhängande betyder kalendertid, inte "tre fakturor" --
    ett avslut och en återkomst startar inte om kampanjen (§6), och det följer
    av att slutdatumet sätts en gång och sedan står fast.
    """
    months = max(0, int(price.intro_months or 0))
    year = first_paid_at.year + (first_paid_at.month - 1 + months) // 12
    month = (first_paid_at.month - 1 + months) % 12 + 1
    day = min(first_paid_at.day, _days_in_month(year, month))
    return first_paid_at.replace(year=year, month=month, day=day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def intro_active(subscription: Subscription | None, now: datetime) -> bool:
    """
    Gäller introduktionspriset just nu?

    Läser subskriptionens sparade fönster, inte kampanjens villkor: fönstret
    sattes en gång när första betalningen lyckades, och ska inte kunna flytta
    sig för att någon ändrar kampanjkonfigurationen efteråt.
    """
    if subscription is None:
        return False
    if not subscription.intro_started_at or not subscription.intro_ends_at:
        return False
    return subscription.intro_started_at <= now < subscription.intro_ends_at


# ---------------------------------------------------------------------------
# Styckpris och månadsbelopp
# ---------------------------------------------------------------------------


def _unit_price_ore(price: PriceVersion, quantity: int, intro: bool) -> tuple[int, str]:
    """(styckpris, skälet). Skälet följer med ut i raden kunden ser."""
    if quantity >= price.volume_threshold:
        tier_price, tier_basis = price.volume_price_ore, "volume"
    else:
        tier_price, tier_basis = price.base_price_ore, "base"

    if not intro:
        return tier_price, tier_basis

    # Kombineras inte: den lägsta gäller, aldrig summan av båda. Se modulens
    # docstring för varför tolkningen ser ut så här.
    if price.intro_price_ore <= tier_price:
        return price.intro_price_ore, "intro"
    return tier_price, tier_basis


def monthly_quote(
    price: PriceVersion,
    *,
    licenses: int,
    extra_counties: int,
    intro: bool,
) -> Quote:
    """
    Det löpande månadsbeloppet för ett givet antal licenser och extra län.

    `extra_counties` är summan över alla bilar (bil A med två extra län och bil
    B med ett ger 3), eftersom priset är per bil OCH extra län.
    """
    licenses = max(0, int(licenses))
    extra_counties = max(0, int(extra_counties))

    unit, basis = _unit_price_ore(price, licenses, intro)
    lines: list[LineItem] = []
    if licenses:
        lines.append(
            LineItem(
                key=f"licenses_{basis}",
                label=_license_label(basis, price),
                quantity=licenses,
                unit_price_ore=unit,
                amount_ore=unit * licenses,
                note=_license_note(basis, price, licenses),
            )
        )
    if extra_counties:
        lines.append(
            LineItem(
                key="extra_counties",
                label="Extra län",
                quantity=extra_counties,
                unit_price_ore=price.extra_county_price_ore,
                amount_ore=price.extra_county_price_ore * extra_counties,
                # Uttryckligt: länstillägg rabatteras inte, varken av volym
                # eller av introduktionen.
                note="Per bil och extra län. Omfattas inte av volymrabatt eller introduktionspris.",
            )
        )

    amount = sum(line.amount_ore for line in lines)
    vat = vat_of(amount, price.vat_rate_bp)
    return Quote(
        currency=price.currency,
        vat_rate_bp=price.vat_rate_bp,
        amount_ore=amount,
        vat_ore=vat,
        total_ore=amount + vat,
        lines=lines,
        price_version=price.id,
    )


def _license_label(basis: str, price: PriceVersion) -> str:
    if basis == "intro":
        return "Billicenser (introduktionspris)"
    if basis == "volume":
        return f"Billicenser (volympris från {price.volume_threshold} bilar)"
    return "Billicenser"


def _license_note(basis: str, price: PriceVersion, licenses: int) -> str:
    if basis == "intro":
        return (
            f"Introduktionspris under företagets första {price.intro_months} "
            "sammanhängande betalmånader. Kombineras inte med volymrabatt."
        )
    if basis == "volume":
        return f"Gäller samtliga {licenses} köpta licenser, inte bara de över gränsen."
    return f"Under {price.volume_threshold} bilar. Från {price.volume_threshold} bilar gäller volympriset."


# ---------------------------------------------------------------------------
# Ändringar: vad kostar det nu, och vad kostar nästa period
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChangeQuote:
    """
    Underlaget kunden ser innan en beställning godkänns: kostnad nu, nästa
    period, moms, totalsumma och datum (§6).
    """

    now: Quote
    next_period: Quote
    current: Quote
    effective_at: datetime | None
    next_period_start: datetime | None
    proration_remaining_seconds: int
    proration_total_seconds: int
    price_version: str

    def as_dict(self) -> dict:
        return {
            "now": self.now.as_dict(),
            "nextPeriod": self.next_period.as_dict(),
            "current": self.current.as_dict(),
            "effectiveAt": self.effective_at.isoformat() if self.effective_at else None,
            "nextPeriodStart": (
                self.next_period_start.isoformat() if self.next_period_start else None
            ),
            "proration": {
                "remainingSeconds": self.proration_remaining_seconds,
                "totalSeconds": self.proration_total_seconds,
            },
            "priceVersion": self.price_version,
        }


def quote_change(
    price: PriceVersion,
    *,
    now: datetime,
    period_start: datetime | None,
    period_end: datetime | None,
    intro_now: bool,
    intro_next_period: bool,
    current_licenses: int,
    current_extra_counties: int,
    new_licenses: int,
    new_extra_counties: int,
    immediate: bool,
) -> ChangeQuote:
    """
    Hela underlaget för en ändring.

    `immediate=True` för uppgraderingar (fler bilar, extra län): de betalas
    proportionellt nu och gäller när betalningen lyckats.
    `immediate=False` för minskningar och baslänsbyten: inget att betala nu,
    ändringen träder i kraft vid nästa förnyelse (§8).

    Beloppet "nu" är aldrig negativt. En minskning ger ingen återbetalning här
    -- den gäller vid nästa förnyelse, och då är det nya månadsbeloppet det som
    faktureras.
    """
    current = monthly_quote(
        price, licenses=current_licenses, extra_counties=current_extra_counties, intro=intro_now
    )
    after = monthly_quote(
        price, licenses=new_licenses, extra_counties=new_extra_counties, intro=intro_now
    )
    next_period = monthly_quote(
        price,
        licenses=new_licenses,
        extra_counties=new_extra_counties,
        intro=intro_next_period,
    )

    if period_start and period_end and period_end > period_start:
        remaining, total = proration_factor(now, period_start, period_end)
    else:
        # Ingen löpande period ännu: det här är företagets FÖRSTA beställning,
        # och då betalas en hel månad i förskott. Att falla tillbaka på
        # proportioneringens "0 av 1 sekund kvar" hade gett beloppet noll --
        # alltså gratis licenser åt den som aldrig haft en period.
        remaining, total = (1, 1)

    if not immediate:
        empty = Quote(
            currency=price.currency, vat_rate_bp=price.vat_rate_bp,
            amount_ore=0, vat_ore=0, total_ore=0, lines=[], price_version=price.id,
        )
        return ChangeQuote(
            now=empty, next_period=next_period, current=current,
            effective_at=period_end, next_period_start=period_end,
            proration_remaining_seconds=remaining, proration_total_seconds=total,
            price_version=price.id,
        )

    delta_lines: list[LineItem] = []
    delta_amount = 0
    for line in _delta_lines(current, after):
        prorated = prorate(line.amount_ore, remaining, total)
        if prorated == 0:
            continue
        delta_amount += prorated
        delta_lines.append(
            LineItem(
                key=f"prorated_{line.key}",
                label=line.label,
                quantity=line.quantity,
                unit_price_ore=line.unit_price_ore,
                amount_ore=prorated,
                note=(
                    f"Proportionellt för återstående del av perioden "
                    f"({_days(remaining)} av {_days(total)} dagar)."
                ),
            )
        )

    # Aldrig en kredit nu: minskningar gäller vid nästa förnyelse.
    if delta_amount < 0:
        delta_amount = 0
        delta_lines = []

    vat = vat_of(delta_amount, price.vat_rate_bp)
    now_quote = Quote(
        currency=price.currency, vat_rate_bp=price.vat_rate_bp,
        amount_ore=delta_amount, vat_ore=vat, total_ore=delta_amount + vat,
        lines=delta_lines, price_version=price.id,
    )
    return ChangeQuote(
        now=now_quote, next_period=next_period, current=current,
        effective_at=now, next_period_start=period_end,
        proration_remaining_seconds=remaining, proration_total_seconds=total,
        price_version=price.id,
    )


def _delta_lines(before: Quote, after: Quote) -> list[LineItem]:
    """
    Skillnaden mellan två månadsbelopp, rad för rad.

    Rader matchas på `key`, så att ett byte av prisnivå (9 -> 10 bilar byter
    `licenses_base` mot `licenses_volume`) ger en korrekt nettoskillnad i
    stället för en dubbel debitering av hela det nya beloppet.
    """
    keys = {line.key for line in before.lines} | {line.key for line in after.lines}
    before_by_key = {line.key: line for line in before.lines}
    after_by_key = {line.key: line for line in after.lines}

    # Byte av prisnivå: summera hela licensdelen i stället för per nyckel.
    license_keys = {k for k in keys if k.startswith("licenses_")}
    out: list[LineItem] = []
    if license_keys:
        before_amount = sum(before_by_key[k].amount_ore for k in license_keys if k in before_by_key)
        after_amount = sum(after_by_key[k].amount_ore for k in license_keys if k in after_by_key)
        if after_amount != before_amount:
            target = next(
                (after_by_key[k] for k in sorted(license_keys) if k in after_by_key), None
            )
            out.append(
                LineItem(
                    key="licenses",
                    label=target.label if target else "Billicenser",
                    quantity=target.quantity if target else 0,
                    unit_price_ore=target.unit_price_ore if target else 0,
                    amount_ore=after_amount - before_amount,
                )
            )
    for key in sorted(keys - license_keys):
        b = before_by_key.get(key)
        a = after_by_key.get(key)
        diff = (a.amount_ore if a else 0) - (b.amount_ore if b else 0)
        if diff == 0:
            continue
        src = a or b
        out.append(
            LineItem(
                key=key, label=src.label,
                quantity=(a.quantity if a else 0) - (b.quantity if b else 0),
                unit_price_ore=src.unit_price_ore, amount_ore=diff,
            )
        )
    return out


def _days(seconds: int) -> int:
    return max(0, round(seconds / 86400))


def default_price_version() -> PriceVersion:
    """
    Prisversionen nya beställningar får. Befintliga avtal pekar på sin egen och
    rörs inte av att en ny läggs till.
    """
    version = PriceVersion.objects.filter(is_default=True).first()
    if version is None:
        raise PriceVersion.DoesNotExist(
            "Ingen förvald prisversion. Kör `manage.py seed_pricing`."
        )
    return version


def next_period_end(period_end: datetime) -> datetime:
    """Nästa förnyelsedatum: en månad framåt, med samma dagklämning som intro."""
    year = period_end.year + (period_end.month) // 12
    month = period_end.month % 12 + 1
    day = min(period_end.day, _days_in_month(year, month))
    return period_end.replace(year=year, month=month, day=day)


__all__ = [
    "ChangeQuote", "LineItem", "Quote", "default_price_version", "intro_active",
    "intro_available", "intro_window", "monthly_quote", "next_period_end",
    "proration_factor", "prorate", "quote_change", "vat_of",
]
