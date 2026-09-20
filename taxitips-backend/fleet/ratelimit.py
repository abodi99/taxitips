"""
Hastighetsbegränsning för registrering, inbjudningar och koder (§7).

**Vad den är och inte är.** Räknaren ligger i Djangos cache (locmem med en
instans, Redis när `CACHE_REDIS_URL` är satt). Den är en broms, inte en
säkerhetsgräns: en tömd cache nollställer den. De riktiga gränserna är
databasens -- `PairingCode.attempts`, kodens femminuterstid, de partiella unika
indexen och provspärrens `org_key`. Den här modulen finns för att en angripare
inte ska kunna mala igenom tusentals koder innan de gränserna hinner bita.

Nyckeln hashas innan den når cachen, så att en e-postadress eller ett
organisationsnummer inte ligger i klartext i Redis.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from django.core.cache import cache


@dataclass(frozen=True)
class Limit:
    key: str
    limit: int
    window_seconds: int


# Startvärden. Alla generösa nog för en verklig administratör med en dålig dag,
# snäva nog att en skriptad gissning slår i taket långt innan den lyckas.
PAIRING_REDEEM = Limit("pairing_redeem", limit=10, window_seconds=300)
PAIRING_ISSUE = Limit("pairing_issue", limit=20, window_seconds=3600)
SIGNUP = Limit("signup", limit=5, window_seconds=3600)
JOIN_LOOKUP = Limit("join_lookup", limit=10, window_seconds=3600)
INVITE_REDEEM = Limit("invite_redeem", limit=10, window_seconds=3600)


def _bucket(limit: Limit, identity: str) -> str:
    digest = hashlib.sha256(f"{limit.key}:{identity}".encode()).hexdigest()[:32]
    return f"fleet:rl:{limit.key}:{digest}"


def hit(limit: Limit, identity: str) -> tuple[bool, int]:
    """
    Räkna ett försök. Returnerar (tillåtet, antal hittills).

    `cache.add` sätter bara om nyckeln saknas, så fönstret börjar vid första
    försöket och förlängs inte av de följande -- annars hade en jämn ström av
    försök hållit spärren öppen i all evighet.
    """
    bucket = _bucket(limit, identity)
    cache.add(bucket, 0, limit.window_seconds)
    try:
        count = cache.incr(bucket)
    except ValueError:
        # Nyckeln hann gå ut mellan add och incr.
        cache.set(bucket, 1, limit.window_seconds)
        count = 1
    return count <= limit.limit, count


def peek(limit: Limit, identity: str) -> int:
    return int(cache.get(_bucket(limit, identity)) or 0)


def reset(limit: Limit, identity: str) -> None:
    cache.delete(_bucket(limit, identity))


class RateLimited(Exception):
    def __init__(self, limit: Limit, count: int):
        super().__init__(limit.key)
        self.limit = limit
        self.count = count
        self.reason = "rate_limited"
        self.message = "För många försök. Vänta en stund och prova igen."


def enforce(limit: Limit, identity: str) -> None:
    allowed, count = hit(limit, identity)
    if not allowed:
        raise RateLimited(limit, count)
