"""
Celerys mjuka tidsgräns får inte fångas som ett vanligt fel.

Pollslingor fångar brett per operatör, flygplats eller hållplats, så att en
som fallerar inte stoppar de andra. Men SoftTimeLimitExceeded är också en
Exception: i integrationskörningen 2026-09-13 fångades den som "otraf:
SoftTimeLimitExceeded()" och rundan fortsatte, tills bara den hårda gränsen
hade kunnat stoppa den. Anropa reraise_time_limit först i varje sådant block.
"""

from __future__ import annotations


def reraise_time_limit(exc: BaseException) -> None:
    from celery.exceptions import SoftTimeLimitExceeded

    if isinstance(exc, SoftTimeLimitExceeded):
        raise exc
