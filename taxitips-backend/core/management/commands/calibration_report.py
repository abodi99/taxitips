"""
Kalibreringsrapporten (core/calibration.py): feedback, notiser och AIS-kajtider
mot utfall. Flyttar inga trösklar.

    python manage.py calibration_report [--days 7] [--json]
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from core import calibration


class Command(BaseCommand):
    help = "Hur väl tips, notiser och kajtider håller -- och om underlaget räcker"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=calibration.DEFAULT_DAYS)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, days, **options):
        report = calibration.build(days=days)
        if options["json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
            return
        window = report["window"]
        self.stdout.write(f"Fönster: {window['days']} dygn · minst {report['minSamples']} utfall per slutsats\n")
        self.stdout.write("Feedback per regel (🚕 / 👍 / 👎, träffkvot):")
        for row in report["feedback"] or [{"rule": "—", "heading": 0, "fare": 0, "empty": 0, "fareRate": None}]:
            self.stdout.write(f"  {row['rule']}: {row['heading']} / {row['fare']} / {row['empty']}, {row['fareRate']}")
        push = report["push"]
        self.stdout.write(f"Notiser: {push['total']} {push['byStatus']} · skickad median {push['sentMedianSeconds']} s")
        self.stdout.write("AIS-anlöp:")
        for row in report["ferry"] or [{"terminal": "—", "calls": 0, "arrived": 0}]:
            self.stdout.write(
                f"  {row['terminal']}: {row['calls']} anlöp, {row['arrived']} framme"
                + (f", förvarning {row['leadMedianMinutes']} min, sista fel {row['lastErrorMedianMinutes']} min"
                   if row.get("arrived") else "")
            )
        self.stdout.write("\nSlutsatser:")
        for note in report["notes"]:
            self.stdout.write(f"  - {note}")
