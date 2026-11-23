"""Säljutskick ur CRM: urval, takt, stoppregler, avregistrering, svar och studsar."""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta
from email.message import EmailMessage
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import Client, override_settings

from fleet import crm, mailer, notifications, outreach, outreach_inbox, outreach_templates
from fleet.management.commands.import_sales_list import Command as ImportCommand
from fleet.models import (
    CrmCampaign,
    CrmCampaignRecipient,
    CrmDeal,
    CrmDealStage,
    CrmEmailSuppression,
    CrmNote,
    CrmTask,
    OutboxMessage,
    StaffRole,
)
from fleet.tests.base import FleetTestCase

State = CrmCampaignRecipient.State
STHLM = ZoneInfo("Europe/Stockholm")
# En tisdag förmiddag, mitt i sändningsfönstret.
TUESDAY = datetime(2026, 11, 24, 10, 0, tzinfo=STHLM)

OUTREACH = override_settings(
    OUTREACH_ENABLED=True,
    OUTREACH_SMTP_USER="abbe@taxitips.test",
    OUTREACH_SMTP_PASSWORD="hemligt",
    OUTREACH_FROM_NAME="Abbe från Taxi Tips",
    OUTREACH_SENDER_NAME="Abbe",
    OUTREACH_SENDER_TITLE="Grundare",
)


class Sender:
    """Står in för SMTP: minns raderna och ger dem ett Message-ID som mailer.send_outreach."""

    def __init__(self, error: Exception | None = None):
        self.rows: list = []
        self.error = error

    def __call__(self, row):
        if self.error:
            raise self.error
        self.rows.append(row)
        payload = dict(row.payload or {})
        payload["message_id"] = f"<{uuid.uuid4().hex}@taxitips.test>"
        row.payload = payload
        OutboxMessage.objects.filter(id=row.id).update(payload=payload)


class OutreachCase(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.campaign = CrmCampaign.objects.create(
            slug="test", name="Test", status=CrmCampaign.Status.ACTIVE, daily_cap=80,
        )
        self.n = 0

    def prospect(
        self, name="Malmö Taxi AB", *, email=None, form="Aktiebolag", segment="a", tier=1,
        org=None, person="Anna Svensson", stage=CrmDealStage.NEW, city="Malmö",
    ):
        self.n += 1
        account = crm.create_account(
            name=name, org_number=org or f"55660{self.n:05d}", county="Skåne län",
            city=city, legal_form=form, source="test",
        )
        address = f"info{self.n}@bolag{self.n}.test" if email is None else email
        contact = crm.create_person(name=person, email=address, account=account) if address or person else None
        deal = crm.create_deal(name=name, account=account, person=contact, stage=stage, source="test")
        crm.set_tags(
            entity_type="account", entity_id=account.id,
            slugs=[f"segment:{segment}", f"call:{tier}"],
        )
        return account, deal

    def enroll(self, **kwargs):
        return outreach.enroll(self.campaign, **kwargs)

    def at(self, moment):
        return mock.patch("django.utils.timezone.now", return_value=moment)

    def tick(self, moment=TUESDAY, sender=None):
        sender = sender or Sender()
        with self.at(moment):
            report = outreach.tick(moment, sender=sender, wait=lambda: None)
        return report, sender


class AudienceTests(OutreachCase):
    def test_only_legal_persons_with_usable_address_are_enrolled(self):
        self.prospect("Bra Taxi AB")
        self.prospect("Enskild Taxi", form="Enskild firma")
        self.prospect("Okänd Taxi", form="")
        self.prospect("Ring Ej AB", segment="x")
        self.prospect("Utan Mejl AB", email="")
        self.prospect("Trasig AB", email="inte-en-adress")
        self.prospect("Färdtjänst AB", email="taxi@malmo.kommun.test")
        self.prospect("Möte AB", stage=CrmDealStage.MEETING)
        self.prospect("Förlorad AB", stage=CrmDealStage.LOST)
        _, spärrad = self.prospect("Spärrad AB", email="nej@sparr.test")
        outreach.suppress("NEJ@sparr.test", outreach.Reason.BLOCKLIST, "reklamspärr")
        self.prospect("Kund AB", org="5566112233")
        self.make_company(name="Kund AB", org_number="556611-2233")

        report = self.enroll()

        self.assertEqual(report["enrolled"], 1)
        self.assertEqual(
            list(self.campaign.recipients.values_list("account__name", flat=True)), ["Bra Taxi AB"],
        )
        skipped = report["skipped"]
        self.assertEqual(skipped["enskild firma eller annan fysisk person"], 1)
        self.assertEqual(skipped["okänd bolagsform"], 1)
        self.assertEqual(skipped["ring ej"], 1)
        self.assertEqual(skipped["ingen e-post"], 1)
        self.assertEqual(skipped["ogiltig e-post"], 1)
        self.assertEqual(skipped["offentlig beställare"], 1)
        self.assertEqual(skipped["säljaren arbetar redan med affären"], 2)
        self.assertEqual(skipped["spärrad adress"], 1)
        self.assertEqual(skipped["redan kund"], 1)

    def test_shared_address_gets_one_mail_and_enroll_is_idempotent(self):
        self.prospect("Central AB", email="vx@central.test")
        self.prospect("Dotter AB", email="VX@central.test")
        self.assertEqual(self.enroll()["enrolled"], 1)
        again = self.enroll()
        self.assertEqual(again["enrolled"], 0)
        self.assertEqual(self.campaign.recipients.count(), 1)

    def test_domains_without_a_mailbox_are_left_out(self):
        self.prospect("Bra AB", email="info@finns.test")
        self.prospect("Felstavad AB", email="vd@hotmail.com_")
        self.prospect("Död Domän AB", email="info@borta.test")
        with mock.patch(
            "fleet.outreach.domain_receives_mail", side_effect=lambda d: d == "finns.test",
        ) as lookup:
            report = self.enroll(check_dns=True, dry_run=True)
        self.assertEqual(report["enrolled"], 1)
        self.assertEqual(report["skipped"]["domänen tar inte emot mejl"], 1)
        self.assertEqual(report["skipped"]["ogiltig e-post"], 1)
        self.assertEqual(lookup.call_count, 2)

    def test_dry_run_writes_nothing_and_segment_filter_applies(self):
        self.prospect("Stor AB", segment="a")
        self.prospect("Liten AB", segment="c")
        report = self.enroll(segments={"a"}, dry_run=True)
        self.assertEqual(report["enrolled"], 1)
        self.assertEqual(report["skipped"], {"annat segment": 1})
        self.assertEqual(self.campaign.recipients.count(), 0)

    def test_segment_a_is_sent_before_segment_c(self):
        self.prospect("Liten AB", segment="c", tier=1)
        self.prospect("Stor AB", segment="a", tier=6)
        self.enroll()
        with self.at(TUESDAY):
            first = outreach.due(TUESDAY, 1)
        self.assertEqual(first[0].account.name, "Stor AB")


class TemplateTests(OutreachCase):
    @OUTREACH
    def test_texts_name_the_company_the_sender_and_the_way_out(self):
        ctx = outreach_templates.Context(
            company="Malmö Taxi AB", place="Malmö", first_name="Anna",
            unsubscribe_url="https://taxitips.se/avregistrera?t=abc", campaign="test",
        )
        for step in (1, 2, 3):
            subject, body = outreach_templates.render(step, ctx)
            self.assertIn("https://taxitips.se/avregistrera?t=abc", body)
            self.assertIn("A2M Tech AB", body)
            self.assertIn("https://taxitips.se/appen?utm_source=mejl&utm_campaign=test", body)
            self.assertNotIn("/registrera", body)
            self.assertIn("Abbe\nGrundare, Taxi Tips", body)
            self.assertEqual(subject.startswith("Re: "), step > 1)
        subject, body = outreach_templates.render(1, ctx)
        self.assertEqual(subject, "Var står era bilar när alla behöver taxi?")
        self.assertIn("Hej Anna,", body)
        self.assertIn("Vill ni på Malmö Taxi AB prova med en bil i Malmö?", body)

    @OUTREACH
    def test_mails_are_short_enough_to_read_at_a_glance(self):
        ctx = outreach_templates.Context(
            company="Malmö Taxi AB", place="Malmö", first_name="Anna", unsubscribe_url="u",
        )
        from dataclasses import replace

        for size in outreach_templates.SIZES:
            for step in (1, 2, 3):
                main = outreach_templates.render(step, replace(ctx, size=size))[1].split("\n-- \n")[0]
                self.assertLess(len(main.split()), 90, f"mejl {step} ({size}) är för långt")

    def test_unknown_name_and_place_read_naturally(self):
        ctx = outreach_templates.Context(company="X AB", place="", first_name="", unsubscribe_url="u")
        subject, body = outreach_templates.render(1, ctx)
        self.assertTrue(body.startswith("Hej X,\n"))
        self.assertIn("Vill ni på X AB prova med en bil? Det kostar inget", body)
        long_name = outreach_templates.Context(
            company="Norra Skånes Buss Och Taxi i Strövelstorp AB", place="", first_name="",
            unsubscribe_url="u",
        )
        self.assertTrue(outreach_templates.render(1, long_name)[1].startswith("Hej,\n"))

    @OUTREACH
    def test_language_is_easy_for_a_second_language_reader(self):
        from dataclasses import replace

        base = outreach_templates.Context(
            company="Malmö Taxi AB", place="Malmö", first_name="Anna", unsubscribe_url="u",
        )
        for size in outreach_templates.SIZES:
            for variant in range(3):
                for step in (1, 2, 3):
                    body = outreach_templates.render(step, replace(base, size=size, variant=variant))[1]
                    text = outreach_templates.prose(body)
                    where = f"mejl {step} ({size}, bild {variant}): {text!r}"
                    self.assertLess(outreach_templates.lix(text), outreach_templates.LIX_MAX, where)
                    self.assertLessEqual(
                        outreach_templates.longest_sentence(text),
                        outreach_templates.SENTENCE_MAX_WORDS, where,
                    )
        # Mätaren själv: en krånglig mening ska falla.
        hard = (
            "Applikationen tillhandahåller realtidsbaserade efterfrågeprognoser avseende "
            "kollektivtrafikstörningar, flygförseningar samt evenemangsavslutningar."
        )
        self.assertGreater(outreach_templates.lix(hard), 60)
        self.assertEqual(outreach_templates.lix_label(22), "mycket lättläst")

    def test_wording_follows_company_size(self):
        make = lambda size: outreach_templates.Context(  # noqa: E731
            company="Ranj Taxi AB", place="Malmö", first_name="Aziz", unsubscribe_url="u", size=size,
        )
        solo_subject, solo = outreach_templates.render(1, make(outreach_templates.SOLO))
        self.assertEqual(solo_subject, "Var står du när alla behöver taxi?")
        self.assertIn("Vill du prova med din bil i Malmö?", solo)
        self.assertNotIn("era förare", solo)
        fleet_subject, fleet = outreach_templates.render(1, make(outreach_templates.FLEET))
        self.assertEqual(fleet_subject, "Var står era bilar när alla behöver taxi?")
        self.assertIn("Vill ni på Ranj Taxi AB prova med en bil i Malmö?", fleet)
        _, large = outreach_templates.render(1, make(outreach_templates.LARGE))
        self.assertIn("visar jag det på tio minuter", large)
        self.assertIn("Ni har många bilar ute samtidigt", large)
        self.assertIn("din telefon", outreach_templates.render(2, make(outreach_templates.SOLO))[1])
        self.assertIn("Du kan börja när du vill", outreach_templates.render(3, make(outreach_templates.SOLO))[1])

    def test_size_comes_from_the_crm_segment(self):
        for name, segment in (("Stor AB", "a"), ("Mellan AB", "b"), ("Liten AB", "c"), ("Okänd AB", "d")):
            self.prospect(name, segment=segment)
        self.enroll()
        sizes = {
            r.account.name: outreach.size_for(r)
            for r in self.campaign.recipients.select_related("account")
        }
        self.assertEqual(sizes, {
            "Stor AB": outreach_templates.LARGE, "Mellan AB": outreach_templates.FLEET,
            "Liten AB": outreach_templates.SOLO, "Okänd AB": outreach_templates.FLEET,
        })

    @OUTREACH
    def test_html_has_a_button_a_signature_and_no_images(self):
        ctx = outreach_templates.Context(
            company="Malmö <Taxi> AB", place="Malmö", first_name="Anna",
            unsubscribe_url="https://taxitips.se/avregistrera?t=abc",
        )
        html = outreach_templates.html_from_text(outreach_templates.render(1, ctx)[1])
        self.assertIn("Malmö &lt;Taxi&gt; AB", html)
        self.assertIn(
            '<a href="https://taxitips.se/appen?utm_source=mejl&amp;utm_campaign=saljmejl"', html,
        )
        self.assertIn(outreach_templates.BUTTON_LABEL, html)
        self.assertEqual(html.count("/appen"), 1)           # knappen ersätter länkraden
        self.assertIn(">Hämta appen</a>", html)
        self.assertIn("<strong", html)                        # signaturen
        self.assertIn(">taxitips.se/avregistrera</a>", html)
        self.assertNotIn("<img", html)
        tip = outreach_templates.html_from_text(outreach_templates.render(2, ctx)[1])
        self.assertIn("Tips i appen", tip)

    def test_opening_scene_varies_but_stays_the_same_for_one_recipient(self):
        base = dict(company="X AB", place="", first_name="", unsubscribe_url="u")
        bodies = {
            outreach_templates.render(1, outreach_templates.Context(**base, variant=v))[1]
            for v in range(6)
        }
        self.assertEqual(len(bodies), 3)
        self.prospect()
        self.enroll()
        recipient = self.campaign.recipients.select_related("campaign", "account", "person").get()
        self.assertEqual(outreach.context_for(recipient), outreach.context_for(recipient))

    def test_first_name_only_when_certain(self):
        account = SimpleNamespace(name="Malmö Taxi AB")
        person = lambda name, title="VD": SimpleNamespace(name=name, title=title)  # noqa: E731
        self.assertEqual(outreach.first_name(person("ANNA SVENSSON"), account), "Anna")
        self.assertEqual(outreach.first_name(person("Karl Erik Svensson"), account), "")
        self.assertEqual(outreach.first_name(person("Malmö Taxi AB"), account), "")
        self.assertEqual(outreach.first_name(person("Anna Svensson", "Revisor"), account), "")
        self.assertEqual(outreach.first_name(None, account), "")

    def test_place_comes_from_the_company_name_before_the_postal_address(self):
        for city in ("Borås", "Vellinge", "Limhamn", "Falkenberg", "Lund"):
            self.prospect(f"Bolag {self.n}", city=city)
        place = lambda name, city: outreach.place_display(  # noqa: E731
            SimpleNamespace(name=name, city=city, county="")
        )
        self.assertEqual(place("Otk Taxi i Borås AB", "Falkenberg"), "Borås")
        self.assertEqual(place("Vellinge Taxi AB", "Trelleborg"), "Vellinge")
        self.assertEqual(place("Limhamns Taxi AB", "Vintrie"), "Limhamn")
        self.assertEqual(place("Lund Åkeri & Taxi AB", "Eslöv"), "Eslöv")
        self.assertEqual(place("Ranj Taxi AB", "MALMÖ"), "Malmö")

    def test_company_name_is_tidied(self):
        self.assertEqual(outreach.company_display("Icab AB,"), "Icab AB")
        self.assertEqual(outreach.company_display("ADRT SERVICE AB"), "Adrt Service AB")
        self.assertEqual(
            outreach.company_display("Kristianstad Taxi & Buss Aktiebolag"), "Kristianstad Taxi & Buss AB",
        )


class PacingTests(OutreachCase):
    def test_window_is_weekday_office_hours(self):
        self.assertTrue(outreach.in_window(TUESDAY))
        self.assertFalse(outreach.in_window(TUESDAY.replace(hour=7)))
        self.assertFalse(outreach.in_window(TUESDAY.replace(hour=15, minute=30)))
        self.assertFalse(outreach.in_window(datetime(2026, 11, 28, 10, 0, tzinfo=STHLM)))  # lördag
        self.assertFalse(outreach.in_window(datetime(2026, 12, 25, 10, 0, tzinfo=STHLM)))  # juldagen

    def test_cap_warms_up_with_sending_days(self):
        self.assertEqual(outreach.daily_cap(80, TUESDAY), 15)
        for days_ago in (1, 2, 3):
            OutboxMessage.objects.create(
                category="outreach_1", to_address="x@y.test", dedupe_key=f"d{days_ago}",
                status=OutboxMessage.Status.SENT, sent_at=TUESDAY - timedelta(days=days_ago),
            )
        self.assertEqual(outreach.daily_cap(80, TUESDAY), 25)
        self.assertEqual(outreach.daily_cap(20, TUESDAY), 20)

    def test_budget_is_spread_over_the_day_and_stops_at_the_cap(self):
        with self.at(TUESDAY):
            self.assertEqual(outreach.tick_budget(80, TUESDAY), 1)
            late = TUESDAY.replace(hour=15, minute=25)
            self.assertEqual(outreach.tick_budget(80, late), outreach.MAX_PER_TICK)
            for i in range(15):
                OutboxMessage.objects.create(
                    category="outreach_1", to_address="x@y.test", dedupe_key=f"t{i}",
                )
            self.assertEqual(outreach.tick_budget(80, late), 0)

    def test_follow_up_dates_skip_weekends(self):
        friday = datetime(2026, 11, 27, 10, 0, tzinfo=STHLM)
        self.assertEqual(outreach.next_send_after(1, friday).date().isoformat(), "2026-12-03")
        self.assertEqual(outreach.next_send_after(2, friday), friday + timedelta(days=9))
        self.assertIsNone(outreach.next_send_after(3, friday))


class TickTests(OutreachCase):
    def test_nothing_happens_until_switched_on(self):
        self.prospect()
        self.enroll()
        self.assertEqual(outreach.tick(TUESDAY), {"skipped": "disabled"})
        self.assertEqual(OutboxMessage.objects.count(), 0)

    def test_first_mail_is_sent_and_recorded(self):
        _, deal = self.prospect()
        self.enroll()
        report, sender = self.tick()
        self.assertEqual(report["sent"], 1)
        recipient = self.campaign.recipients.get()
        self.assertEqual((recipient.step, recipient.state), (1, State.ACTIVE))
        self.assertEqual(recipient.next_send_at.astimezone(STHLM).date().isoformat(), "2026-11-30")
        self.assertTrue(recipient.thread_message_id.startswith("<"))
        row = OutboxMessage.objects.get()
        self.assertEqual((row.category, row.status), ("outreach_1", OutboxMessage.Status.SENT))
        self.assertEqual(row.payload["deal_id"], str(deal.id))
        self.assertIn("/api/crm/avregistrera/", row.payload["one_click_url"])
        self.assertIn("Hej Anna,", row.body)
        self.assertEqual(outreach.messages(deal_id=deal.id)["total"], 1)

    def test_same_recipient_is_not_mailed_twice_and_follow_up_threads(self):
        self.prospect()
        self.enroll()
        self.tick()
        report, _ = self.tick(TUESDAY + timedelta(minutes=10))
        self.assertEqual(report["sent"], 0)
        later = datetime(2026, 11, 30, 10, 30, tzinfo=STHLM)
        report, sender = self.tick(later)
        self.assertEqual(report["sent"], 1)
        row = sender.rows[0]
        recipient = self.campaign.recipients.get()
        self.assertEqual(row.category, "outreach_2")
        self.assertTrue(row.subject.startswith("Re: "))
        self.assertEqual(row.payload["thread"], recipient.thread_message_id)
        self.assertEqual(recipient.step, 2)

    def test_series_ends_after_three_and_campaign_is_done(self):
        self.prospect()
        self.enroll()
        moment = TUESDAY
        for _ in range(3):
            self.tick(moment)
            recipient = self.campaign.recipients.get()
            moment = (recipient.next_send_at or moment) + timedelta(minutes=5)
            while not outreach.in_window(moment):
                moment += timedelta(hours=1)
        recipient = self.campaign.recipients.get()
        self.assertEqual((recipient.step, recipient.state), (3, State.FINISHED))
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, CrmCampaign.Status.DONE)
        self.assertEqual(OutboxMessage.objects.count(), 3)

    def test_outside_window_and_paused_campaign_send_nothing(self):
        self.prospect()
        self.enroll()
        report, _ = self.tick(TUESDAY.replace(hour=20))
        self.assertEqual(report["skipped"], "outside_window")
        outreach.pause(self.campaign, "test", alert=False)
        report, _ = self.tick()
        self.assertEqual(report["skipped"], "no_active_campaign")
        self.assertEqual(OutboxMessage.objects.count(), 0)

    def test_follow_up_stops_when_salesperson_takes_over(self):
        _, deal = self.prospect()
        self.enroll()
        self.tick()
        CrmDeal.objects.filter(id=deal.id).update(stage=CrmDealStage.MEETING)
        report, sender = self.tick(datetime(2026, 11, 30, 10, 30, tzinfo=STHLM))
        self.assertEqual((report["sent"], report["stopped"]), (0, 1))
        self.assertEqual(self.campaign.recipients.get().state, State.STOPPED)

    def test_started_trial_counts_as_result_and_stops_series(self):
        account, _ = self.prospect(org="5566998877")
        self.enroll()
        self.tick()
        self.make_company(name="Malmö Taxi AB", org_number="556699-8877")
        report, _ = self.tick(TUESDAY + timedelta(minutes=10))
        self.assertEqual(report["converted"], 1)
        self.assertEqual(self.campaign.recipients.get().state, State.CONVERTED)
        self.assertEqual(outreach.stats(self.campaign, TUESDAY)["converted"], 1)

    def test_refused_recipient_is_suppressed(self):
        self.prospect(email="borta@bolag.test")
        self.enroll()
        report, _ = self.tick(sender=Sender(mailer.RecipientRefused("550 finns inte")))
        self.assertEqual(report["failed"], 1)
        self.assertTrue(outreach.is_suppressed("borta@bolag.test"))
        self.assertEqual(self.campaign.recipients.get().state, State.BOUNCED)
        # En adress som inte finns är mottagarens fel, inte kampanjens.
        self.campaign.refresh_from_db()
        self.assertNotEqual(self.campaign.status, CrmCampaign.Status.PAUSED)

    def test_other_permanent_failure_pauses_the_campaign(self):
        self.prospect("Ett AB")
        self.prospect("Två AB")
        self.enroll()
        with mock.patch("fleet.outreach._alert") as alert:
            self.tick(
                TUESDAY.replace(hour=15, minute=25),
                sender=Sender(mailer.PermanentMailError("SMTP 554: sändgräns")),
            )
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, CrmCampaign.Status.PAUSED)
        self.assertIn("sändgräns", self.campaign.paused_reason)
        self.assertEqual(OutboxMessage.objects.count(), 1)
        self.assertFalse(CrmEmailSuppression.objects.exists())
        alert.assert_called_once()

    def test_many_bounces_pause_the_campaign(self):
        for i in range(20):
            OutboxMessage.objects.create(
                category="outreach_1", to_address=f"a{i}@b.test", dedupe_key=f"g{i}",
                status=OutboxMessage.Status.SENT, sent_at=TUESDAY - timedelta(days=1),
                payload={"campaign_id": str(self.campaign.id)},
            )
        for i in range(2):
            CrmCampaignRecipient.objects.create(
                campaign=self.campaign, email=f"a{i}@b.test", state=State.BOUNCED,
                stopped_at=TUESDAY - timedelta(hours=3),
            )
        self.assertIn("2 studsar på 20 mejl", outreach.guard(self.campaign, TUESDAY))
        with mock.patch("fleet.outreach._alert"):
            report, _ = self.tick()
        self.assertEqual(report["skipped"], "no_active_campaign")


class UnsubscribeTests(OutreachCase):
    def setUp(self):
        super().setUp()
        self.prospect(email="info@malmotaxi.test")
        self.enroll()
        self.tick()
        self.recipient = self.campaign.recipients.get()
        self.url = f"/api/crm/avregistrera/{outreach.token_for(self.recipient)}"

    def test_post_unsubscribes_and_stops_the_series(self):
        response = Client().post(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(
            CrmEmailSuppression.objects.get().reason, CrmEmailSuppression.Reason.UNSUBSCRIBED,
        )
        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.state, State.UNSUBSCRIBED)
        report, sender = self.tick(datetime(2026, 11, 30, 10, 30, tzinfo=STHLM))
        self.assertEqual(sender.rows, [])
        self.assertEqual(Client().post(self.url).status_code, 200)

    def test_get_only_redirects_so_link_scanners_cannot_unsubscribe(self):
        response = Client().get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("https://taxitips.se/avregistrera?t=", response["Location"])
        self.assertFalse(CrmEmailSuppression.objects.exists())

    def test_forged_link_is_rejected(self):
        token = outreach.token_for(self.recipient)
        forged = token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")
        for bad in ("inte-en-token", forged):
            response = Client().post(f"/api/crm/avregistrera/{bad}")
            self.assertEqual(response.status_code, 404)
        self.assertFalse(CrmEmailSuppression.objects.exists())
        self.assertLess(len(token), 70)
        self.assertNotIn(":", token)

    def test_not_enabled_without_a_named_sender(self):
        with override_settings(
            OUTREACH_ENABLED=True, OUTREACH_SMTP_USER="a@taxitips.test",
            OUTREACH_SMTP_PASSWORD="x", OUTREACH_SENDER_NAME="",
        ):
            self.assertFalse(outreach.enabled())
        with OUTREACH:
            self.assertTrue(outreach.enabled())

    def test_queued_mail_is_not_sent_after_unsubscribe(self):
        row = notifications.queue(
            category="outreach_2", to_address="info@malmotaxi.test", subject="s", body="b",
            key_parts=("efter",),
        )
        CrmEmailSuppression.objects.create(email="info@malmotaxi.test", reason="unsubscribed")
        sender = Sender()
        self.assertEqual(notifications.deliver(row, sender=sender), "suppressed")
        self.assertEqual(sender.rows, [])
        row.refresh_from_db()
        self.assertEqual(row.status, OutboxMessage.Status.SUPPRESSED)

    def test_service_mail_ignores_the_marketing_block(self):
        CrmEmailSuppression.objects.create(email="kund@bolag.test", reason="unsubscribed")
        row = notifications.queue(
            category="payment_failed", to_address="kund@bolag.test", subject="s", body="b",
            key_parts=("tjanst",),
        )
        sender = Sender()
        self.assertEqual(notifications.deliver(row, sender=sender), "sent")
        self.assertEqual(len(sender.rows), 1)


class MessageTests(OutreachCase):
    @OUTREACH
    def test_headers_allow_one_click_unsubscribe_and_threading(self):
        row = SimpleNamespace(
            category="outreach_2", to_address="info@malmotaxi.test", subject="Re: Hej",
            body="Hej\n\n-- \nSidfot",
            payload={
                "one_click_url": "https://backend.taxitips.se/api/crm/avregistrera/tok",
                "thread": "<forsta@taxitips.test>",
            },
        )
        message = mailer.build_outreach(row)
        headers = message.extra_headers
        self.assertEqual(
            headers["List-Unsubscribe"],
            "<https://backend.taxitips.se/api/crm/avregistrera/tok>, "
            "<mailto:abbe@taxitips.test?subject=Avregistrera>",
        )
        self.assertEqual(headers["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        self.assertEqual(headers["In-Reply-To"], "<forsta@taxitips.test>")
        self.assertTrue(headers["Message-ID"].endswith("@taxitips.test>"))
        self.assertEqual(message.from_email, "Abbe från Taxi Tips <abbe@taxitips.test>")
        self.assertEqual(message.reply_to, ["abbe@taxitips.test"])
        self.assertEqual(message.alternatives[0][1], "text/html")

    @OUTREACH
    def test_sent_copy_is_built_with_crlf_line_endings(self):
        # IMAP APPEND kräver CRLF. Kopian i Skickat byggs ur det färdiga mejlet.
        row = SimpleNamespace(
            category="outreach_1", to_address="info@malmotaxi.test", subject="Hej Malmö",
            body="Hej Anna,\n\nåäö på två rader.\n\n-- \nSidfot", payload={},
        )
        raw = mailer.wire_bytes(mailer.build_outreach(row))
        self.assertIn(b"\r\n\r\n", raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertIn(b"To: info@malmotaxi.test\r\n", raw)

    @OUTREACH
    def test_send_stores_a_copy_in_the_sent_folder(self):
        row = OutboxMessage.objects.create(
            category="outreach_1", to_address="info@malmotaxi.test", dedupe_key="kopia",
            subject="Hej Malmö", body="Hej Anna,\n\n-- \nSidfot", payload={},
        )
        with mock.patch.object(mailer, "_deliver") as deliver, \
                mock.patch.object(outreach_inbox, "append_sent", return_value=True) as append:
            mailer.send_outreach(row)
        deliver.assert_called_once()
        (raw,), _ = append.call_args
        self.assertIsInstance(raw, bytes)
        self.assertIn(b"Subject: Hej", raw)
        row.refresh_from_db()
        self.assertTrue(row.payload["message_id"].endswith("@taxitips.test>"))

    @OUTREACH
    def test_test_send_sends_all_three_and_stores_copies(self):
        out = io.StringIO()
        with mock.patch.object(mailer, "_deliver") as deliver, \
                mock.patch.object(outreach_inbox, "append_sent", return_value=True) as append:
            call_command("outreach", "test-send", to="du@exempel.test", stdout=out)
        self.assertEqual(deliver.call_count, 3)
        self.assertEqual(append.call_count, 3)
        for (raw,), _ in append.call_args_list:
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertEqual(out.getvalue().count("(kopia i Skickat)"), 3)

    def test_unconfigured_mailbox_is_retried_not_dropped(self):
        row = SimpleNamespace(category="outreach_1", to_address="a@b.test", payload={})
        with self.assertRaises(RuntimeError) as caught:
            mailer.send(row)
        self.assertNotIsInstance(caught.exception, mailer.PermanentMailError)


def reply(sender, text, *, references="", **headers) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "abbe@taxitips.test"
    message["Subject"] = "Re: Era bilar i Malmö mellan körningarna"
    if references:
        message["In-Reply-To"] = references
    for key, value in headers.items():
        message[key.replace("_", "-")] = value
    message.set_content(text)
    return message


class InboxTests(OutreachCase):
    def setUp(self):
        super().setUp()
        _, self.deal = self.prospect(email="info@malmotaxi.test")
        self.enroll()
        self.tick()
        self.recipient = self.campaign.recipients.get()

    def handle(self, message):
        return outreach_inbox.apply(outreach_inbox.classify(message), subject=str(message["Subject"]))

    def test_reply_stops_series_and_lands_with_the_salesperson(self):
        outcome = self.handle(reply(
            "Anna Svensson <INFO@malmotaxi.test>",
            "Hej! Det låter intressant, ring mig.\n\nDen 24 nov. 2026 skrev Abbe:\n> Hej Anna,",
        ))
        self.assertEqual(outcome, "reply")
        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.state, State.REPLIED)
        self.assertIsNone(self.recipient.next_send_at)
        note = CrmNote.objects.get(title="Svar på säljmejl")
        self.assertIn("ring mig", note.body)
        self.assertNotIn("> Hej Anna", note.body)
        task = CrmTask.objects.get()
        self.assertEqual(task.deal_id, self.deal.id)
        self.assertFalse(outreach.is_suppressed("info@malmotaxi.test"))

    def test_reply_from_colleague_is_matched_on_the_thread(self):
        outcome = self.handle(reply(
            "vd@annandoman.test", "Vi hör av oss.", references=self.recipient.thread_message_id,
        ))
        self.assertEqual(outcome, "reply")
        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.state, State.REPLIED)

    def test_no_thanks_is_an_unsubscribe(self):
        outcome = self.handle(reply("info@malmotaxi.test", "Nej tack, vi är inte intresserade."))
        self.assertEqual(outcome, "opt_out")
        self.assertTrue(outreach.is_suppressed("info@malmotaxi.test"))
        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.state, State.UNSUBSCRIBED)
        self.assertFalse(CrmTask.objects.exists())

    def test_auto_reply_changes_nothing(self):
        outcome = self.handle(reply("info@malmotaxi.test", "Jag är på semester.", Auto_Submitted="auto-replied"))
        self.assertEqual(outcome, "auto")
        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.state, State.ACTIVE)

    def test_hard_bounce_suppresses_the_address(self):
        bounce = EmailMessage()
        bounce["From"] = "Mail Delivery System <MAILER-DAEMON@hostinger.test>"
        bounce["To"] = "abbe@taxitips.test"
        bounce["Subject"] = "Undelivered Mail Returned to Sender"
        bounce.set_content(
            "This is the mail system.\n\nFinal-Recipient: rfc822; info@malmotaxi.test\n"
            "Action: failed\nStatus: 5.1.1\n"
        )
        self.assertEqual(self.handle(bounce), "bounce")
        self.assertEqual(CrmEmailSuppression.objects.get().reason, CrmEmailSuppression.Reason.BOUNCED)
        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.state, State.BOUNCED)

    def test_soft_bounce_and_strangers_are_left_alone(self):
        soft = EmailMessage()
        soft["From"] = "postmaster@hostinger.test"
        soft.set_content("Final-Recipient: rfc822; info@malmotaxi.test\nStatus: 4.2.2\n")
        self.assertEqual(self.handle(soft), "soft_bounce")
        self.assertEqual(self.handle(reply("okand@annan.test", "Hej")), "unknown_sender")
        self.assertFalse(CrmEmailSuppression.objects.exists())
        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.state, State.ACTIVE)


class AdminApiTests(OutreachCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.staff_user = uuid.uuid4()
        StaffRole.objects.create(user_id=self.staff_user, role=StaffRole.Role.SALES)
        _, self.deal = self.prospect()
        self.enroll()
        self.tick()

    def as_staff(self):
        return mock.patch("fleet.admin_crm._staff", return_value=mock.Mock(
            user_id=self.staff_user, email="sales@taxitips.test",
        ))

    def test_overview_lists_campaign_numbers_messages_and_texts(self):
        with self.as_staff():
            data = self.client.get("/api/admin/crm/outreach").json()
        campaign = data["campaigns"][0]
        self.assertEqual((campaign["sent"], campaign["inSequence"]), (1, 1))
        self.assertEqual(campaign["sentPerStep"], {"1": 1, "2": 0, "3": 0})
        self.assertEqual(data["messages"]["total"], 1)
        self.assertEqual(len(data["templates"]), 9)
        message_id = data["messages"]["rows"][0]["id"]
        with self.as_staff():
            message = self.client.get(f"/api/admin/crm/outreach/messages/{message_id}").json()
        self.assertIn("Vänliga hälsningar", message["message"]["body"])

    def test_deal_shows_its_mail(self):
        with self.as_staff():
            data = self.client.get(f"/api/admin/crm/deals/{self.deal.id}").json()
        self.assertEqual(data["mail"]["state"], State.ACTIVE)
        self.assertEqual(len(data["mail"]["messages"]), 1)

    def test_pause_and_resume(self):
        url = f"/api/admin/crm/outreach/campaigns/{self.campaign.id}"
        with self.as_staff():
            paused = self.client.post(url, data='{"action": "pause"}', content_type="application/json").json()
            self.assertEqual(paused["campaign"]["status"], "paused")
            resumed = self.client.post(url, data='{"action": "resume"}', content_type="application/json").json()
            self.assertEqual(resumed["campaign"]["status"], "active")
            bad = self.client.post(url, data='{"action": "radera"}', content_type="application/json")
        self.assertEqual(bad.status_code, 400)


class ImportFlagTests(OutreachCase):
    def test_flagged_rows_are_suppressed_on_import(self):
        command = ImportCommand()
        command._upsert_row(
            {
                "name": "Spärr Taxi AB", "orgnr": "5566001122", "email": "Info@Sparr.test",
                "legal_form": "Aktiebolag", "segment": "B",
                "flags": ["Reklamspärr (Allabolag) – inga utskick"],
            },
            checkpoint={}, skip_notes=True,
        )
        command._upsert_row(
            {"name": "Fri Taxi AB", "orgnr": "5566001133", "email": "info@fri.test", "segment": "B"},
            checkpoint={}, skip_notes=True,
        )
        self.assertTrue(outreach.is_suppressed("info@sparr.test"))
        self.assertFalse(outreach.is_suppressed("info@fri.test"))
