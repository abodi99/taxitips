"""
Säljutskicken från kommandoraden (fleet/outreach.py).

  python manage.py outreach preview                      # de tre mejlen som text
  python manage.py outreach test-send --to du@exempel.se # skickar dem till dig
  python manage.py outreach enroll --campaign taxibolag-2026 --segments a --dry-run
  python manage.py outreach enroll --campaign taxibolag-2026 --segments a
  python manage.py outreach start --campaign taxibolag-2026
  python manage.py outreach pause --campaign taxibolag-2026
  python manage.py outreach status
  python manage.py outreach tick                         # en körning nu

`enroll` lägger bolag i kö; ingenting går förrän kampanjen är startad och
OUTREACH_ENABLED=1. `--dry-run` visar vilka som kommer med och varför resten
föll bort, utan att skriva något.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError

from fleet import mailer, outreach, outreach_inbox, outreach_templates
from fleet.models import CrmCampaign

SAMPLE = outreach_templates.Context(
    company="Exempel Taxi AB", place="Malmö", first_name="Anna",
    unsubscribe_url="https://taxitips.se/avregistrera?t=exempel",
)


class Command(BaseCommand):
    help = "Säljutskick ur CRM: förhandsvisa, testa, lägg i kö, starta, pausa."

    def add_arguments(self, parser):
        parser.add_argument(
            "action",
            choices=["preview", "test-send", "enroll", "start", "pause", "status", "tick"],
        )
        parser.add_argument("--campaign", default="", help="Kampanjens slug")
        parser.add_argument("--name", default="", help="Kampanjens namn (när den skapas)")
        parser.add_argument("--segments", default="", help="t.ex. a,b (tomt = alla)")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--cap", type=int, default=0, help="Dagstak efter uppvärmning")
        parser.add_argument("--to", default="", help="Mottagare för test-send")
        parser.add_argument("--step", type=int, default=0, help="Bara ett steg (1-3)")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--no-dns", action="store_true",
            help="Hoppa över kontrollen att mottagarens domän tar emot mejl",
        )

    def handle(self, *args, **opts):
        return getattr(self, "_" + opts["action"].replace("-", "_"))(opts)

    def _steps(self, opts) -> range | list[int]:
        step = int(opts["step"] or 0)
        if step and not 1 <= step <= outreach_templates.STEP_COUNT:
            raise CommandError("--step ska vara 1-3")
        return [step] if step else range(1, outreach_templates.STEP_COUNT + 1)

    def _campaign(self, opts, *, create: bool = False) -> CrmCampaign:
        slug = (opts["campaign"] or "").strip()
        if not slug:
            raise CommandError("Ange --campaign")
        campaign = CrmCampaign.objects.filter(slug=slug).first()
        if campaign is None:
            if not create:
                raise CommandError(f"Kampanjen {slug} finns inte")
            campaign = CrmCampaign(slug=slug, name=opts["name"] or slug)
            if opts["cap"]:
                campaign.daily_cap = opts["cap"]
            if not opts["dry_run"]:
                campaign.save()
        elif opts["cap"] and not opts["dry_run"]:
            campaign.daily_cap = opts["cap"]
            campaign.save(update_fields=["daily_cap", "updated_at"])
        return campaign

    def _preview(self, opts):
        from dataclasses import replace

        for size in outreach_templates.SIZES:
            for step in self._steps(opts):
                subject, body = outreach_templates.render(step, replace(SAMPLE, size=size))
                self.stdout.write(
                    f"\n===== Mejl {step}, {outreach_templates.SIZE_LABEL[size]} =====\n"
                    f"Ämne: {subject}\n\n{body}\n"
                )

    def _test_send(self, opts):
        to = (opts["to"] or "").strip()
        if not outreach.valid_email(to):
            raise CommandError("Ange --to med en giltig adress")
        if not mailer.outreach_configured():
            raise CommandError("Säljbrevlådan är inte inlagd (OUTREACH_SMTP_USER/-PASSWORD)")
        if not outreach_templates.sender_name():
            raise CommandError("Avsändarens namn saknas (OUTREACH_SENDER_NAME)")
        thread = ""
        for step in self._steps(opts):
            subject, body = outreach_templates.render(step, SAMPLE)
            row = SimpleNamespace(
                category=f"{outreach.CATEGORY_PREFIX}{step}", to_address=to,
                subject=subject, body=body,
                payload={
                    "one_click_url": "https://backend.taxitips.se/api/crm/avregistrera/exempel",
                    "thread": thread,
                },
            )
            message = mailer.build_outreach(row, connection=mailer._outreach_connection())
            mailer._deliver(message)
            thread = thread or message.extra_headers["Message-ID"]
            saved = outreach_inbox.append_sent(message.message().as_bytes(linesep="\r\n"))
            self.stdout.write(
                f"Mejl {step} skickat till {to} från {mailer.outreach_from()}"
                + (" (kopia i Skickat)" if saved else " (ingen kopia i Skickat)")
            )

    def _enroll(self, opts):
        campaign = self._campaign(opts, create=True)
        segments = {s.strip().lower() for s in opts["segments"].split(",") if s.strip()} or None
        report = outreach.enroll(
            campaign, segments=segments, limit=opts["limit"], dry_run=opts["dry_run"],
            check_dns=not opts["no_dns"],
        )
        self.stdout.write(
            f"{'Skulle lägga' if opts['dry_run'] else 'Lade'} {report['enrolled']} bolag i kö "
            f"för {campaign.slug} (status: {campaign.get_status_display()})."
        )
        for reason, count in sorted(report["skipped"].items(), key=lambda kv: -kv[1]):
            self.stdout.write(f"  utesluts: {count:>5}  {reason}")
        for line in report.get("sample", []):
            self.stdout.write(f"  först i kön: {line}")

    def _start(self, opts):
        campaign = self._campaign(opts)
        outreach.resume(campaign)
        note = "" if outreach.enabled() else (
            " OBS: inget skickas förrän OUTREACH_ENABLED=1, brevlådan och "
            "OUTREACH_SENDER_NAME är inlagda."
        )
        self.stdout.write(self.style.SUCCESS(f"{campaign.slug} är aktiv.{note}"))

    def _pause(self, opts):
        campaign = self._campaign(opts)
        outreach.pause(campaign, "pausad från kommandoraden", alert=False)
        self.stdout.write(f"{campaign.slug} är pausad.")

    def _status(self, opts):
        self.stdout.write(
            f"Påslaget: {'ja' if outreach.enabled() else 'nej'}  "
            f"Brevlåda: {mailer.outreach_address() or '(saknas)'}"
        )
        for campaign in CrmCampaign.objects.order_by("created_at"):
            s = outreach.stats(campaign)
            self.stdout.write(
                f"{s['slug']} [{s['status']}] mottagare={s['recipients']} väntar={s['waiting']} "
                f"pågår={s['inSequence']} skickade={s['sent']} svar={s['replied']} "
                f"avreg={s['unsubscribed']} studs={s['bounced']} prov={s['converted']} "
                f"idag={s['usedToday']}/{s['capToday']}"
                + (f" pausad: {s['pausedReason']}" if s["pausedReason"] else "")
            )

    def _tick(self, opts):
        if not outreach.enabled():
            raise CommandError(
                "Avstängt: sätt OUTREACH_ENABLED=1 och lägg in brevlådan och OUTREACH_SENDER_NAME"
            )
        self.stdout.write(f"inkorg={outreach_inbox.poll()}")
        self.stdout.write(f"utskick={outreach.tick()}")
