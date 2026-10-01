"""Inbyggd CRM — separat modul (account/person/deal), ingen billing-synk."""

from __future__ import annotations

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
