"""
Kvalitetsgranskning av tipsen (core/tip_audit.py). Rent läsande.

    python manage.py audit_tips              # aktiva tips
    python manage.py audit_tips --hours 24   # även de som startat senaste dygnet
    python manage.py audit_tips --json
    python manage.py audit_tips --strict     # exit 1 vid fel (för CI/healthcheck)
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from core import tip_audit


class Command(BaseCommand):
    help = "Granskar att aktiva tips har rätt betyg, förklaring och tider"

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=0)
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--strict", action="store_true")

    def handle(self, *args, hours, **options):
        report = tip_audit.audit(hours=hours)
        if options["json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(
                f"{report['tips']} tips ({report['scope']}) · "
                f"{report['errors']} fel · {report['warnings']} varningar\n"
            )
            for c in report["checks"]:
                mark = "OK " if c["count"] == 0 else c["severity"].upper()[:3]
                self.stdout.write(f"  [{mark}] {c['title']}: {c['count']}")
                if c["count"]:
                    self.stdout.write(f"        {c['why']}")
                    for ex in c["examples"][:3]:
                        extra = {k: v for k, v in ex.items()
                                 if k not in ("id", "externalId", "title", "mode", "tier", "score")}
                        self.stdout.write(
                            f"        – {ex['title'][:70]} ({ex['mode']}, {ex['tier']}, {ex['score']} p)"
                            + (f" {extra}" if extra else "")
                        )
        if options["strict"] and not report["ok"]:
            raise CommandError(f"{report['errors']} fel i tipsen")
