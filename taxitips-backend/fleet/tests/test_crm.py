"""Inbyggd CRM — separat modul (account/person/deal), ingen billing-synk."""

from __future__ import annotations

import io
import json
import uuid
from unittest import mock

from django.test import Client

from fleet import crm
from fleet.models import CrmDeal, CrmDealStage, CrmNote, StaffRole
from fleet.tests.base import FleetTestCase


class CrmLogicTests(FleetTestCase):
    def test_ingest_deduplicates_open_deal_by_email(self):
        first = crm.ingest_web_lead(
            name="Anna", email="anna@example.test", message="Hej, vi är intresserade av prov.",
        )
        second = crm.ingest_web_lead(
            name="Anna", email="anna@example.test", message="Uppföljning från webben.",
        )
        self.assertEqual(first.id, second.id)
        self.assertIn("Uppföljning", second.notes_summary)
        self.assertEqual(first.stage, CrmDealStage.NEW)

    def test_registration_does_not_create_crm_rows(self):
        before = CrmDeal.objects.count()
        company = self.make_company(name="Ingen CRM AB", org_number="5566003344")
        self.assertEqual(CrmDeal.objects.count(), before)
        self.assertIsNone(crm.deal_for_company(company.id))

    def test_manual_link_sets_company_id(self):
        deal = crm.ingest_web_lead(
            name="Bo", email="bo@example.test", company="Bo Taxi",
            message="Vill ha demo snart tack.",
        )
        company = self.make_company(name="Bo Taxi AB", org_number="5566004455")
        crm.link_deal_to_company(deal, company.id, stage=CrmDealStage.WON)
        deal.refresh_from_db()
        self.assertEqual(deal.company_id, company.id)
        self.assertEqual(deal.stage, CrmDealStage.WON)


class CrmAdminApiTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.staff_user = uuid.uuid4()
        StaffRole.objects.create(user_id=self.staff_user, role=StaffRole.Role.SALES)

    def as_staff(self):
        return mock.patch("fleet.admin_crm._staff", return_value=mock.Mock(
            user_id=self.staff_user, email="sales@taxitips.test",
        ))

    def test_pipeline_and_company_note(self):
        deal = crm.ingest_web_lead(
            name="Weblead", email="lead@example.test", company="Lead AB",
            message="Intresserad av Taxitips för flottan.",
        )
        company = self.make_company(name="Kund AB", org_number="5566005566")
        with self.as_staff():
            pipe = self.client.get("/api/admin/crm/pipeline").json()
            self.assertTrue(pipe["ok"])
            ids = [r["id"] for r in pipe["rows"]]
            self.assertIn(str(deal.id), ids)
            note_res = self.client.post(
                f"/api/admin/companies/{company.id}/crm/notes",
                data=json.dumps({"title": "Samtal", "body": "Ringde och bokade demo."}),
                content_type="application/json",
            )
        self.assertTrue(note_res.json()["ok"])
        self.assertEqual(
            CrmNote.objects.filter(company_id=company.id).count(),
            1,
        )

    def test_deal_stage_update(self):
        deal = crm.create_deal(name="Sälj", stage=CrmDealStage.NEW)
        with self.as_staff():
            res = self.client.post(
                f"/api/admin/crm/deals/{deal.id}/update",
                data=json.dumps({"stage": CrmDealStage.SCREENING}),
                content_type="application/json",
            )
        self.assertTrue(res.json()["ok"])
        deal.refresh_from_db()
        self.assertEqual(deal.stage, CrmDealStage.SCREENING)

    def test_board_endpoint(self):
        crm.create_deal(name="Board", stage=CrmDealStage.MEETING)
        with self.as_staff():
            res = self.client.get("/api/admin/crm/pipeline?board=1").json()
        self.assertTrue(res["ok"])
        self.assertIn("columns", res)
        ids = [c["id"] for c in res["columns"]]
        self.assertIn(CrmDealStage.MEETING, ids)


class CrmPipelineFilterTests(FleetTestCase):
    """Filter i pipeline_deals/pipeline_page — alla AND:as server-side."""

    def _deal(self, name, *, city="", form="", stage=CrmDealStage.NEW,
              tags=(), phone="", email=""):
        account = crm.create_account(name=name, city=city, legal_form=form)
        person = crm.create_person(
            name=f"Kontakt {name}", phone=phone, email=email, account=account,
        )
        deal = crm.create_deal(name=name, account=account, person=person, stage=stage)
        if tags:
            crm.set_tags(entity_type="account", entity_id=account.id, slugs=list(tags))
        return deal

    def _names(self, **filters):
        return {r["name"] for r in crm.pipeline_page(**filters)["rows"]}

    def setUp(self):
        super().setUp()
        self._deal("Malmö Taxi", city="Malmö", form="Aktiebolag",
                   tags=["segment:a", "lan:12", "call:1"], phone="040-1")
        self._deal("Lund Bil", city="Lund", form="Enskild firma",
                   tags=["segment:c", "lan:12", "call:1"], email="lund@example.test")
        self._deal("Göteborg Åkeri", city="Göteborg", form="Aktiebolag",
                   tags=["segment:a", "lan:14", "medlem:taxiforbundet"])
        self._deal("Malmö Stängd", city="Malmö", form="Aktiebolag",
                   tags=["segment:a", "lan:12"], stage=CrmDealStage.LOST)

    def test_city_and_legal_form(self):
        self.assertEqual(self._names(city="malmö"), {"Malmö Taxi"})
        self.assertEqual(self._names(legal_form="Aktiebolag"),
                         {"Malmö Taxi", "Göteborg Åkeri"})
        self.assertEqual(self._names(legal_form="enskild firma"), {"Lund Bil"})

    def test_tags_are_anded(self):
        self.assertEqual(self._names(tags=["lan:12"]), {"Malmö Taxi", "Lund Bil"})
        self.assertEqual(self._names(tags=["lan:12", "segment:a"]), {"Malmö Taxi"})
        self.assertEqual(self._names(tags=["medlem:taxiforbundet"]), {"Göteborg Åkeri"})
        self.assertEqual(self._names(tags=["segment:x"]), set())

    def test_q_stage_tag_city_combined(self):
        self.assertEqual(self._names(q="malmö"), {"Malmö Taxi"})
        self.assertEqual(
            self._names(stage=CrmDealStage.LOST, q="malmö", tags=["segment:a"], city="Malmö"),
            {"Malmö Stängd"},
        )
        self.assertEqual(self._names(q="göteborg", tags=["lan:12"]), set())
        # Fritextsök träffar även ort.
        self.assertEqual(self._names(q="Lund"), {"Lund Bil"})

    def test_has_phone_and_email(self):
        self.assertEqual(self._names(has_phone=True), {"Malmö Taxi"})
        self.assertEqual(self._names(has_email=True), {"Lund Bil"})
        self.assertEqual(self._names(has_phone=True, has_email=True), set())

    def test_contact_on_account_counts_for_phone(self):
        deal = self._deal("Extra Kontakt", city="Ystad")
        crm.create_person(name="Växel", phone="0411-1", account=deal.account)
        self.assertIn("Extra Kontakt", self._names(has_phone=True))

    def test_pagination_total_and_offset(self):
        first = crm.pipeline_page(limit=2)
        self.assertEqual(first["total"], 3)
        self.assertEqual(len(first["rows"]), 2)
        rest = crm.pipeline_page(limit=2, offset=2)
        self.assertEqual(len(rest["rows"]), 1)
        ids = {r["id"] for r in first["rows"]} | {r["id"] for r in rest["rows"]}
        self.assertEqual(len(ids), 3)

    def _order(self, sort, **filters):
        return [r["name"] for r in crm.pipeline_page(sort=sort, **filters)["rows"]]

    def test_sort_by_name_uses_swedish_order(self):
        self._deal("Åby Taxi", city="Åby")
        self._deal("Zeta Taxi", city="Zinkgruvan")
        names = self._order("name")
        self.assertEqual(names[0], "Göteborg Åkeri")
        self.assertEqual(names[-2:], ["Zeta Taxi", "Åby Taxi"])
        self.assertEqual(self._order("-name")[0], "Åby Taxi")
        cities = [r["account"]["city"] for r in crm.pipeline_page(sort="city")["rows"]]
        self.assertEqual(cities[-1], "Åby")

    def test_sort_by_priority_tier_then_segment(self):
        # Tier 1: Malmö (A) före Lund (C); Göteborg saknar tier → sist.
        self.assertEqual(
            self._order("priority"), ["Malmö Taxi", "Lund Bil", "Göteborg Åkeri"],
        )

    def test_sort_by_stage_and_unknown_falls_back(self):
        self.assertEqual(self._order("stage", stage=CrmDealStage.LOST), ["Malmö Stängd"])
        self.assertEqual(len(self._order("nonsens")), 3)

    def test_stage_counts_follow_filters(self):
        page = crm.pipeline_page(city="Malmö")
        counts = page["stageCounts"]
        self.assertEqual(counts[CrmDealStage.NEW], 1)
        self.assertEqual(counts[CrmDealStage.LOST], 1)
        self.assertEqual(counts[""], 1)
        self.assertEqual(page["total"], 1)

    def test_rows_carry_account_tags(self):
        row = next(r for r in crm.pipeline_page()["rows"] if r["name"] == "Göteborg Åkeri")
        slugs = {t["slug"] for t in row["tags"]}
        self.assertEqual(slugs, {"segment:a", "lan:14", "medlem:taxiforbundet"})

    def test_facets(self):
        facets = crm.pipeline_facets()
        self.assertEqual(facets["cities"], ["Göteborg", "Lund", "Malmö"])
        self.assertEqual(facets["legalForms"], ["Aktiebolag", "Enskild firma"])
        self.assertIn("lan:12", [t["slug"] for t in facets["counties"]])
        self.assertIn("call:1", [t["slug"] for t in facets["callTiers"]])


class CrmPipelineApiFilterTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.staff_user = uuid.uuid4()
        StaffRole.objects.create(user_id=self.staff_user, role=StaffRole.Role.SALES)
        for name, city, slugs, phone in [
            ("Skåne A", "Malmö", ["segment:a", "lan:12"], "040-1"),
            ("Skåne C", "Malmö", ["segment:c", "lan:12"], ""),
            ("Sthlm A", "Solna", ["segment:a", "lan:01"], "08-1"),
        ]:
            account = crm.create_account(name=name, city=city, legal_form="Aktiebolag")
            person = crm.create_person(name=name, phone=phone, account=account)
            crm.create_deal(name=name, account=account, person=person)
            crm.set_tags(entity_type="account", entity_id=account.id, slugs=slugs)

    def get(self, qs):
        with mock.patch("fleet.admin_crm._staff", return_value=mock.Mock(
            user_id=self.staff_user, email="sales@taxitips.test",
        )):
            return self.client.get(f"/api/admin/crm/pipeline?{qs}").json()

    def test_repeated_tag_and_city(self):
        res = self.get("tag=segment:a&tag=lan:12")
        self.assertTrue(res["ok"])
        self.assertEqual([r["name"] for r in res["rows"]], ["Skåne A"])
        self.assertEqual(res["tags"], ["segment:a", "lan:12"])
        res = self.get("city=Malm%C3%B6&phone=1")
        self.assertEqual([r["name"] for r in res["rows"]], ["Skåne A"])
        self.assertEqual(res["rows"][0]["account"]["city"], "Malmö")
        self.assertEqual(res["rows"][0]["account"]["legalForm"], "Aktiebolag")

    def test_limit_and_facets(self):
        res = self.get("limit=1&form=Aktiebolag")
        self.assertEqual(res["total"], 3)
        self.assertEqual(len(res["rows"]), 1)
        self.assertEqual(res["facets"]["cities"], ["Malmö", "Solna"])

    def test_sort_param(self):
        res = self.get("sort=-name")
        self.assertEqual(res["sort"], "-name")
        self.assertEqual([r["name"] for r in res["rows"]], ["Sthlm A", "Skåne C", "Skåne A"])
        self.assertEqual(res["stageCounts"][""], 3)

    def test_bad_limit_falls_back(self):
        res = self.get("limit=abc&offset=-5")
        self.assertTrue(res["ok"])
        self.assertEqual(res["offset"], 0)
        self.assertEqual(res["total"], 3)


class ImportSalesListTests(FleetTestCase):
    def test_reimport_fills_city_and_legal_form(self):
        import tempfile
        from pathlib import Path

        from django.core.management import call_command

        from fleet.models import CrmAccount, CrmTagging

        row = {
            "name": "Testtaxi Malmö", "legal_name": "Testtaxi AB", "orgnr": "556600-1122",
            "legal_form": "Aktiebolag", "city": "Malmö", "county": "Skåne",
            "phone": "040-123", "email": "info@testtaxi.test", "website": None,
            "decision_makers": [{"name": "Eva", "role": "VD"}],
            "segment": "A – Beställningscentral / stort bolag", "call_tier": 1,
            "taxiforbundet": True, "brief": "Ring Eva.",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sales_list.json"
            # Första körningen saknar ort/form — som en import före 0017.
            path.write_text(json.dumps([{**row, "city": "", "legal_form": None}]))
            call_command("import_sales_list", path=str(path), stdout=io.StringIO())
            acc = CrmAccount.objects.get(org_number="5566001122")
            self.assertEqual((acc.city, acc.legal_form), ("", ""))

            path.write_text(json.dumps([row]))
            call_command("import_sales_list", path=str(path), stdout=io.StringIO())
            call_command("import_sales_list", path=str(path), stdout=io.StringIO())

        self.assertEqual(CrmAccount.objects.filter(org_number="5566001122").count(), 1)
        acc.refresh_from_db()
        self.assertEqual((acc.city, acc.legal_form), ("Malmö", "Aktiebolag"))
        self.assertEqual(CrmDeal.objects.filter(account=acc).count(), 1)
        slugs = set(CrmTagging.objects.filter(
            entity_type="account", entity_id=acc.id,
        ).values_list("tag__slug", flat=True))
        self.assertTrue({"lan:12", "segment:a", "call:1", "medlem:taxiforbundet"} <= slugs)
        names = {
            r["name"] for r in crm.pipeline_page(
                city="Malmö", legal_form="Aktiebolag",
                tags=["lan:12", "medlem:taxiforbundet"], has_phone=True, has_email=True,
            )["rows"]
        }
        self.assertEqual(names, {"Testtaxi Malmö"})


class WebLeadApiTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()

    def post_lead(self, body, origin="https://taxitips.se"):
        return self.client.post(
            "/api/crm/lead",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_ORIGIN=origin,
        )

    def test_newsletter_writes_crm_and_reach(self):
        with mock.patch("fleet.crm_ingest.reach.save_contact", return_value={"ok": True, "created": True}) as save:
            res = self.post_lead({
                "kind": "newsletter",
                "email": "nyhet@example.test",
                "company": "Nyhetsbolaget",
            })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Access-Control-Allow-Origin"], "https://taxitips.se")
        body = res.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["reach"]["created"])
        deal = CrmDeal.objects.get(id=body["leadId"])
        self.assertEqual(deal.source, "taxitips_web_newsletter")
        self.assertIn("nyhetsbrevet", deal.notes_summary)
        save.assert_called_once()
        self.assertEqual(save.call_args.kwargs["email"], "nyhet@example.test")
        self.assertEqual(save.call_args.kwargs["tag"], "8b16c070-1283-4fde-875e-8ffe497183eb")

    def test_contact_requires_a_message_and_uses_the_meeting_tag(self):
        short = self.post_lead({
            "kind": "contact",
            "name": "Ada",
            "email": "ada@example.test",
            "message": "kort",
        })
        self.assertEqual(short.status_code, 422)

        with mock.patch("fleet.crm_ingest.reach.save_contact", return_value={"ok": True, "created": True}) as save:
            res = self.post_lead({
                "kind": "contact",
                "name": "Ada",
                "email": "ada@example.test",
                "company": "Ada Taxi",
                "message": "Vi vill boka en genomgång nästa vecka.",
            })
        self.assertEqual(res.status_code, 200)
        deal = CrmDeal.objects.get(id=res.json()["leadId"])
        self.assertEqual(deal.source, "taxitips_web_contact")
        self.assertIn("genomgång", deal.notes_summary)
        self.assertEqual(save.call_args.kwargs["tag"], "624a0bc8-1dc9-4933-9686-f192e8fb27d8")

    def test_reach_failure_keeps_the_crm_lead(self):
        with mock.patch("fleet.crm_ingest.reach.save_contact", side_effect=RuntimeError("reach_500")):
            res = self.post_lead({
                "kind": "newsletter",
                "email": "fel@example.test",
            })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])
        self.assertEqual(res.json()["reach"]["reason"], "reach_failed")
        self.assertTrue(CrmDeal.objects.filter(person__email="fel@example.test").exists())
