"""
Ett lås per återkommande task, så att två körningar av samma jobb aldrig
överlappar.

Beat lägger en poll i kön var 90:e sekund oavsett om förra rundan är klar.
Med två worker-processer kan en långsam runda och nästa köra samtidigt och
skriva samma rader -- och två push-cykler kan välja samma kandidat innan
någon av dem hunnit sätta `notified_at`, och skicka den två gånger. Låset
ligger i Redis, som workern ändå kräver som broker.

Låset har en livslängd (taskens hårda tidsgräns plus marginal): en worker som
dödas mitt i en runda får inte låsa jobbet för alltid.
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager

from django.conf import settings

PREFIX = "taxitips:lock:"

# Släpp bara ett lås vi själva håller. Har vårt gått ut och en annan runda
# tagit det, är det deras.
_RELEASE = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) end return 0"
)


def _client():
    import redis

    return redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_timeout=5, socket_connect_timeout=5)


@contextmanager
def single_run(name: str, ttl_seconds: int, wait_seconds: float = 0, client=None):
    """
    Ger True om låset togs och False om en annan körning redan håller det.
    `wait_seconds` väntar in en pågående körning i stället för att ge upp direkt.
    """
    client = client or _client()
    key = PREFIX + name
    token = uuid.uuid4().hex
    deadline = time.monotonic() + wait_seconds
    acquired = bool(client.set(key, token, nx=True, ex=ttl_seconds))
    while not acquired and time.monotonic() < deadline:
        time.sleep(1)
        acquired = bool(client.set(key, token, nx=True, ex=ttl_seconds))
    try:
        yield acquired
    finally:
        if acquired:
            client.eval(_RELEASE, 1, key, token)
