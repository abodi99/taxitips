"""
Marknadsfokus: vilken region en störning hör till.

Port av worker/src/skane.js. Named market.py, not skane.py -- MARKET_SCOPE
isn't Skåne-only conceptually (the Node file's own comments already
anticipate national rollout), even though the default market and its data
(SKANE_PLACES etc.) still are.
"""

from __future__ import annotations

import re

from django.conf import settings

SKANE_PLACES: set[str] = {
    s.lower()
    for s in [
        "malmö", "lund", "helsingborg", "kristianstad", "hässleholm",
        "landskrona", "ystad", "trelleborg", "eslöv", "ängelholm",
        "höganäs", "höör", "osby", "simrishamn", "sjöbo", "staffanstorp",
        "svedala", "burlöv", "kävlinge", "bromölla", "perstorp",
        "örkelljunga", "bjuv", "åstorp", "klippan", "lomma", "vellinge",
        "hyllie", "triangeln", "malmö c", "lund c", "helsingborg c",
        "hässleholm c",
        "köpenhamns flygplats",  # Öresundståg -> taxibehov på skånska sidan
        "cph", "kastrup",
    ]
}

# Python's re is Unicode-aware by default for str patterns, so plain \b
# likely already handles å/ä/ö starts correctly here (unlike JS's ASCII-only
# \b, which silently broke every entry beginning with å/ä/ö -- öresundståg,
# ängelholm -- in the original). Ported as the same explicit lookaround
# anyway: that's the version actually tested against real data, and "the
# workaround probably isn't needed in Python" is not the same claim as
# "verified safe to remove" -- see core/test_market.py.
_SV = "a-zà-öø-ÿ0-9"


def _sv_word(alternatives: str) -> re.Pattern:
    return re.compile(rf"(?<![{_SV}])(?:{alternatives})(?![{_SV}])", re.IGNORECASE)


SKANE_TEXT_RE = _sv_word(
    "skåne|skånetrafiken|pågatåg|öresundståg|malmö|lund|helsingborg|"
    "kristianstad|hässleholm|landskrona|ystad|trelleborg|eslöv|ängelholm|"
    "hyllie|triangeln|e6|e22|e65"
)

# Places that positively identify an alert as belonging to a DIFFERENT
# region -- an exclusion list, not an allow-list: it only rejects on
# positive evidence of elsewhere, so an alert naming no city still passes.
# See skane.js's own comment for why this exists (Skånetrafiken runs
# Öresundståg/Pågatåg services far outside the county).
NON_SKANE_TEXT_RE = _sv_word(
    "kalmar|nybro|växjö|karlskrona|karlshamn|halmstad|varberg|göteborg|"
    "stockholm|uppsala|örebro|västerås|linköping|norrköping|jönköping|"
    "borås|umeå|luleå|sundsvall|gävle|falun|karlstad"
)


def place_looks_skane(name: str | None) -> bool:
    if not name:
        return False
    n = str(name).lower().strip()
    if n in SKANE_PLACES:
        return True
    return any(n in p or p in n for p in SKANE_PLACES)


def is_national_scope() -> bool:
    """
    MARKET_SCOPE=national disables region filtering: every alert is in
    *someone's* market, and relevance becomes the client's distance
    question (worth_it_score, "Nära mig"), not an ingest-side geofence.
    Default stays "skane" so existing deployments don't change behaviour.
    """
    return str(getattr(settings, "MARKET_SCOPE", "skane") or "skane").lower() == "national"


def configured_regions() -> list[str]:
    """
    The regions that count as "this market" in non-national scope. Mirrors
    trafiklab.py's configured_operators() -- kept in sync by reading the
    same setting rather than importing, so this module stays free of a
    dependency on the fetcher.
    """
    raw = str(getattr(settings, "TRAFIKLAB_OPERATORS", "skane") or "skane")
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


def alert_in_market(alert: dict, taxi: dict | None = None) -> bool:
    """
    True om alerten hör till marknaden (ort, text eller operatör).
    I national-läge är allt inom marknaden -- se is_national_scope().

    `taxi` carries the scored `places` (mirrors Node's alert.taxi.places,
    attached by enrichAlert before this gate runs) -- pass the result of
    score_alert()/score_road_alert() here, not None, for real alerts.
    """
    if not alert:
        return False
    if is_national_scope():
        return True

    text = f"{alert.get('header') or ''} {alert.get('description') or ''} {alert.get('cause') or ''}"

    # Checked before every "yes" path below: an alert naming another
    # region's hub is out even if it also mentions Skåne, and even if it
    # arrived on the skane endpoint (which, on the Sweden feed family,
    # means nothing).
    if NON_SKANE_TEXT_RE.search(text) and not SKANE_TEXT_RE.search(text):
        return False

    region = str(alert.get("region") or "").lower()
    if region in ("skane", "skåne"):
        return True

    places = [*(taxi.get("places") or [] if taxi else []), *(alert.get("areas") or [])]
    if any(place_looks_skane(p) for p in places):
        return True

    if SKANE_TEXT_RE.search(text):
        return True

    # Placeless transit alerts are kept rather than guessed away -- but
    # "keep what we can't place" must not become "keep everything". Scoped
    # to sources actually part of this market: alerts whose region is one
    # of the configured operators, or that carry no region at all. A
    # source declaring an unconfigured region falls through to False and
    # needs MARKET_SCOPE=national to be admitted (see test_market.py's
    # "SL leak" regression case).
    is_road = alert.get("source_kind") == "road" or str(alert.get("id") or "").startswith("tv:")
    if not is_road and (not region or region in configured_regions()):
        return True

    return False
