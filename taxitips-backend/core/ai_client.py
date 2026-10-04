"""
Den enda vägen ut till språkmodellen (Gemini via Genkit).

Varje anrop går hit, oavsett syfte (granskning, faktautdrag, andra bedömning
före notis, förarbesked, nattrapport), och varje anrop:

1. prövas mot avstängningsknappen (`TAXITIPS_AI=off`), dagstaket på antal
   anrop och månadsbudgeten i kronor (core/thresholds.py);
2. körs mot en LÅST modellversion med temperatur 0;
3. loggas i `ai_call` med tokens, kostnad och svarstid -- lyckat eller inte.

Stängd, över taket eller fel: `AiUnavailable` eller modellens eget undantag.
Anroparen behåller då regelsvaret -- AI:n är ett tillägg till reglerna, aldrig
en förutsättning för att ett tips ska finnas eller en notis gå.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone
from pydantic import BaseModel

from core import thresholds
from core.models import AiCall

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 30.0

_instances: dict[str, object] = {}


class AiUnavailable(RuntimeError):
    """AI:n används inte just nu: avstängd, saknar nyckel eller över budget."""


def api_key() -> str | None:
    """Miljövariabeln, annars backendens .env (lokalt och i äldre containrar)."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key.strip()
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("GEMINI_API_KEY="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    return None


def cost_micro_usd(model: str, tokens_in: int, tokens_out: int) -> int:
    price_in, price_out = thresholds.AI_PRICE_USD_PER_MTOK.get(model, thresholds.AI_PRICE_FALLBACK)
    # Pris per miljon tokens gånger tokens = miljondels dollar.
    return round(tokens_in * price_in + tokens_out * price_out)


def kronor(micro_usd: int) -> float:
    return micro_usd / 1_000_000 * thresholds.AI_USD_SEK


def spend(now=None) -> dict:
    """Dagens anrop och månadens kostnad -- budgetens och admins underlag."""
    now = timezone.localtime(now or timezone.now())
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)
    today = AiCall.objects.filter(created_at__gte=day_start).aggregate(n=Count("id"))
    month = AiCall.objects.filter(created_at__gte=month_start).aggregate(
        n=Count("id"), cost=Sum("cost_micro_usd"),
    )
    return {
        "callsToday": today["n"] or 0,
        "callsMonth": month["n"] or 0,
        "costMonthKr": round(kronor(month["cost"] or 0), 2),
        "budgetKr": thresholds.AI_MONTHLY_BUDGET_KR,
        "dailyCallCap": thresholds.AI_DAILY_CALL_CAP,
    }


def unavailable_reason(now=None, purpose: str = "") -> str | None:
    """Varför AI:n inte får användas just nu, eller None."""
    if getattr(settings, "TAXITIPS_AI", "on") == "off":
        return "avstängd (TAXITIPS_AI=off)"
    if not api_key():
        return "GEMINI_API_KEY saknas"
    last_minute = AiCall.objects.filter(
        created_at__gte=(now or timezone.now()) - timedelta(seconds=60),
    ).count()
    # Grinden före en notis är det enda tidskritiska anropet: de sista platserna
    # i minuten är hennes, så att besked och granskning aldrig tränger undan den.
    cap = thresholds.AI_MAX_CALLS_PER_MINUTE
    if purpose != "gate":
        cap -= thresholds.AI_GATE_RESERVED_PER_MINUTE
    if last_minute >= cap:
        return f"minuttaket nått ({cap} anrop per minut för {purpose or 'det här'})"
    used = spend(now)
    if used["callsToday"] >= thresholds.AI_DAILY_CALL_CAP:
        return f"dagstaket nått ({thresholds.AI_DAILY_CALL_CAP} anrop)"
    if used["costMonthKr"] >= thresholds.AI_MONTHLY_BUDGET_KR:
        return f"månadsbudgeten nådd ({thresholds.AI_MONTHLY_BUDGET_KR} kr)"
    return None


def _genkit(model: str):
    """En Genkit-instans per modell, återanvänd mellan anropen."""
    if model in _instances:
        return _instances[model]
    from genkit import Genkit
    from genkit_google_genai import GoogleAI

    qualified = f"googleai/{model}"

    class _DirectGoogleAI(GoogleAI):
        """Löser modellen direkt, utan GET /v1beta/models (som avvisar AQ.-nycklar)."""

        async def init(self):
            action = self._resolve_model(qualified)
            return [action] if action else []

    instance = Genkit(plugins=[_DirectGoogleAI(api_key=api_key())], model=qualified)
    _instances[model] = instance
    return instance


def _run(model: str, prompt: str, schema: type[BaseModel], timeout: float):
    ai = _genkit(model)

    async def _call():
        return await asyncio.wait_for(
            ai.generate(
                model=f"googleai/{model}",
                prompt=prompt,
                output_schema=schema,
                config={"temperature": 0},
            ),
            timeout,
        )

    response = asyncio.run(_call())
    usage = response.usage
    tokens_in = int(getattr(usage, "input_tokens", 0) or 0)
    tokens_out = int(getattr(usage, "output_tokens", 0) or 0) + int(getattr(usage, "thoughts_tokens", 0) or 0)
    return response.output, tokens_in, tokens_out


# Testerna byter ut transporten: (model, prompt, schema, timeout) -> (output, in, out).
transport: Callable = _run


def generate(
    purpose: str,
    prompt: str,
    schema: type[BaseModel],
    *,
    model: str | None = None,
    subject: str = "",
    timeout: float = DEFAULT_TIMEOUT_S,
) -> BaseModel:
    """
    Ett anrop, mot schemat. Kastar AiUnavailable när AI:n inte får användas,
    annars modellens eget undantag vid fel -- båda loggas, ingen av dem tyst.
    """
    reason = unavailable_reason(purpose=purpose)
    if reason:
        raise AiUnavailable(reason)
    model = model or thresholds.AI_MODEL_EXTRACT
    started = time.monotonic()
    try:
        output, tokens_in, tokens_out = transport(model, prompt, schema, timeout)
    except Exception as exc:
        AiCall.objects.create(
            purpose=purpose, model=model, ok=False, subject=subject[:200],
            latency_ms=int((time.monotonic() - started) * 1000),
            error=f"{type(exc).__name__}: {exc}"[:200],
        )
        raise
    if isinstance(output, dict):
        output = schema.model_validate(output)
    AiCall.objects.create(
        purpose=purpose, model=model, ok=True, subject=subject[:200],
        tokens_in=tokens_in, tokens_out=tokens_out,
        cost_micro_usd=cost_micro_usd(model, tokens_in, tokens_out),
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    return output


def json_caller(
    purpose: str, schema: type[BaseModel], *, model: str | None = None, subject: str = "",
    timeout: float = DEFAULT_TIMEOUT_S,
) -> Callable[[str], str]:
    """`call_model(prompt) -> str` för core/genkit.review, som läser JSON."""

    def call(prompt: str) -> str:
        return generate(
            purpose, prompt, schema, model=model, subject=subject, timeout=timeout,
        ).model_dump_json()

    return call


def purge(before_days: int = 90) -> int:
    """Kostnadsloggen behöver inte mer än ett kvartal."""
    deleted, _ = AiCall.objects.filter(created_at__lt=timezone.now() - timedelta(days=before_days)).delete()
    return deleted
