"""
Samma kontroll som /health/pipeline, som exit-kod.

    python manage.py check_pipeline          # 0 = frisk, 1 = inte frisk
    python manage.py check_pipeline --json

Användbar som healthcheck i worker- och beat-containern, som saknar HTTP.
Se core/pipeline_health.py för vad som räknas som friskt.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from core.pipeline_health import evaluate


class Command(BaseCommand):
    help = "Kontrollerar beat-hjärtslaget och kärnkällornas senaste lyckade hämtning"

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        report = evaluate()
        if options["json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            beat = report["heartbeatAgeSeconds"]
            self.stdout.write(f"hjärtslag: {'saknas' if beat is None else f'{beat} s sedan'}")
            for s in report["sources"]:
                age = s["lastSuccessAgeMinutes"]
                self.stdout.write(
                    f"  {s['source']:<18} {'kärna' if s['core'] else 'tillägg':<8} "
                    f"{'INAKTUELL' if s['stale'] else 'ok':<10} "
                    f"senast lyckad: {'aldrig' if age is None else f'{age} min sedan'} "
                    f"(gräns {s['maxAgeMinutes']} min, {s['consecutiveFailures']} fel i rad)"
                )
        if not report["ok"]:
            raise CommandError("inte frisk: " + ", ".join(report["problems"]))
