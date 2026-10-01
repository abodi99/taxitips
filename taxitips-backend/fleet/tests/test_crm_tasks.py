"""CRM: uppgifter, kontakter och redigerade anteckningar — ingen billing-koppling."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from unittest import mock

from django.test import Client
from django.utils import timezone

from fleet import crm, crm_tasks
from fleet.models import AuditEvent, CrmPerson, CrmTask, CrmTaskStatus, KnownAccount, StaffRole
from fleet.tests.base import FleetTestCase


class CrmApiBase(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.seller = uuid.uuid4()
        self.other = uuid.uuid4()
        StaffRole.objects.create(user_id=self.seller, role=StaffRole.Role.SALES)
        StaffRole.objects.create(user_id=self.other, role=StaffRole.Role.SALES)
        KnownAccount.objects.create(
            user_id=self.seller, email="anna@taxitips.test", last_seen_at=timezone.now(),
        )
        KnownAccount.objects.create(
            user_id=self.other, email="bo@taxitips.test", last_seen_at=timezone.now(),
        )
        account = crm.create_account(name="Malmö Taxi AB", city="Malmö")
        person = crm.create_person(name="Eva", phone="040-1", account=account)
        self.deal = crm.create_deal(name="Malmö Taxi AB", account=account, person=person)

    def as_staff(self, user_id=None):
        return mock.patch("fleet.admin_crm._staff", return_value=mock.Mock(
            user_id=user_id or self.seller,
        ))

    def get(self, url, user_id=None):
        with self.as_staff(user_id):
            return self.client.get(url).json()

    def post(self, url, body, user_id=None):
        with self.as_staff(user_id):
            return self.client.post(
                url, data=json.dumps(body), content_type="application/json",
            ).json()


class CrmTaskTests(CrmApiBase):
    def test_create_defaults_to_creator_and_links_deal(self):
        res = self.post("/api/admin/crm/tasks/create", {
            "title": "Ring Eva", "dueDate": crm_tasks.today().isoformat(),
            "dealId": str(self.deal.id),
        })
        self.assertTrue(res["ok"], res)
        task = CrmTask.objects.get(id=res["task"]["id"])
        self.assertEqual(task.assignee_user_id, self.seller)
        self.assertEqual(task.assignee_label, "anna@taxitips.test")
        self.assertEqual(task.account_id, self.deal.account_id)
        self.assertEqual(task.person_id, self.deal.person_id)
        self.assertEqual(res["task"]["bucket"], "today")
        detail = self.get(f"/api/admin/crm/deals/{self.deal.id}")
        self.assertEqual([t["title"] for t in detail["tasks"]], ["Ring Eva"])
        self.assertIn("anna@taxitips.test", [s["email"] for s in detail["staff"]])

    def test_validation(self):
        res = self.post("/api/admin/crm/tasks/create", {"title": " "})
        self.assertEqual(res["reason"], "title_required")
        res = self.post("/api/admin/crm/tasks/create", {"title": "x", "dueDate": "imorgon"})
        self.assertEqual(res["reason"], "invalid_date")
        res = self.post("/api/admin/crm/tasks/create", {
            "title": "x", "assigneeUserId": str(uuid.uuid4()),
        })
        self.assertEqual(res["reason"], "invalid_assignee")

    def test_status_done_sets_completed_and_back(self):
        task = crm_tasks.create_task(title="Skicka offert", assignee_user_id=self.seller)
        res = self.post(f"/api/admin/crm/tasks/{task.id}/update", {"status": "done"})
        self.assertEqual(res["task"]["status"], "done")
        task.refresh_from_db()
        self.assertIsNotNone(task.completed_at)
        self.post(f"/api/admin/crm/tasks/{task.id}/update", {"status": "doing"})
        task.refresh_from_db()
        self.assertIsNone(task.completed_at)
        res = self.post(f"/api/admin/crm/tasks/{task.id}/update", {"status": "glömd"})
        self.assertEqual(res["reason"], "invalid_status")

    def test_reassign_and_delete(self):
        task = crm_tasks.create_task(title="Boka demo", assignee_user_id=self.seller)
        self.post(f"/api/admin/crm/tasks/{task.id}/update", {"assigneeUserId": str(self.other)})
        task.refresh_from_db()
        self.assertEqual(task.assignee_label, "bo@taxitips.test")
        self.assertTrue(self.post(f"/api/admin/crm/tasks/{task.id}/delete", {})["ok"])
        self.assertFalse(CrmTask.objects.filter(id=task.id).exists())
        self.assertTrue(AuditEvent.objects.filter(action="crm_task_deleted").exists())

    def test_dashboard_buckets_and_per_seller(self):
        day = crm_tasks.today()
        mk = crm_tasks.create_task
        mk(title="Försenad", due_date=(day - timedelta(days=2)).isoformat(), assignee_user_id=self.seller)
        mk(title="Idag", due_date=day.isoformat(), assignee_user_id=self.seller)
        mk(title="Veckan", due_date=(day + timedelta(days=3)).isoformat(), assignee_user_id=self.seller)
        mk(title="Utan datum", assignee_user_id=self.seller, status=CrmTaskStatus.DOING)
        mk(title="Klar", assignee_user_id=self.seller, status=CrmTaskStatus.DONE)
        mk(title="Bos", due_date=(day - timedelta(days=1)).isoformat(), assignee_user_id=self.other)
        mk(title="Ingen", assignee_user_id=None)

        mine = self.get("/api/admin/crm/tasks")
        self.assertEqual(mine["assignee"], "me")
        s = mine["summary"]
        self.assertEqual(
            (s["open"], s["overdue"], s["today"], s["week"], s["nodate"], s["doing"], s["doneWeek"]),
            (4, 1, 1, 1, 1, 1, 1),
        )
        self.assertEqual(
            [r["title"] for r in mine["rows"]], ["Försenad", "Idag", "Veckan", "Utan datum"],
        )
        per = {r["email"] or r["userId"]: r for r in mine["perSeller"]}
        self.assertEqual(per["anna@taxitips.test"]["overdue"], 1)
        self.assertEqual(per["bo@taxitips.test"]["open"], 1)
        self.assertEqual(per["none"]["open"], 1)

        self.assertEqual(len(self.get("/api/admin/crm/tasks?assignee=all")["rows"]), 6)
        self.assertEqual(
            [r["title"] for r in self.get("/api/admin/crm/tasks?assignee=none")["rows"]], ["Ingen"],
        )
        done = self.get("/api/admin/crm/tasks?status=done")
        self.assertEqual([r["title"] for r in done["rows"]], ["Klar"])
        theirs = self.get(f"/api/admin/crm/tasks?assignee={self.other}")
        self.assertEqual([r["title"] for r in theirs["rows"]], ["Bos"])

    def test_company_summary_includes_tasks(self):
        company = self.make_company(name="Kund AB", org_number="5566007788")
        crm.link_deal_to_company(self.deal, company.id)
        res = self.post("/api/admin/crm/tasks/create", {
            "title": "Uppföljning efter start", "companyId": str(company.id),
        })
        self.assertEqual(res["task"]["dealId"], str(self.deal.id))
        summary = crm.crm_summary_for_company(company.id)
        self.assertEqual([t["title"] for t in summary["tasks"]], ["Uppföljning efter start"])


class CrmNoteEditTests(CrmApiBase):
    def test_edit_note_keeps_history(self):
        note = crm.create_note(body="Ring efter lunch", deal_id=self.deal.id)
        res = self.post(f"/api/admin/crm/notes/{note.id}/update", {
            "title": "Samtal", "body": "Ring efter 14",
        })
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["note"]["body"], "Ring efter 14")
        self.assertEqual(res["note"]["editedByLabel"], "anna@taxitips.test")
        self.assertIsNotNone(res["note"]["editedAt"])
        event = AuditEvent.objects.get(action="crm_note_edited")
        self.assertEqual(event.detail["before"]["body"], "Ring efter lunch")

    def test_empty_body_rejected(self):
        note = crm.create_note(body="Text", deal_id=self.deal.id)
        res = self.post(f"/api/admin/crm/notes/{note.id}/update", {"body": "  "})
        self.assertEqual(res["reason"], "body_required")
        note.refresh_from_db()
        self.assertEqual(note.body, "Text")

    def test_new_note_author_is_staff_email(self):
        res = self.post(f"/api/admin/crm/deals/{self.deal.id}/notes", {"body": "Hej"})
        self.assertEqual(res["note"]["authorLabel"], "anna@taxitips.test")


class CrmContactTests(CrmApiBase):
    def url(self, suffix=""):
        return f"/api/admin/crm/deals/{self.deal.id}/contacts{suffix}"

    def test_add_contact_and_set_primary(self):
        res = self.post(self.url(), {"name": "Olle", "email": "olle@ex.test", "title": "VD"})
        self.assertTrue(res["ok"], res)
        names = [c["name"] for c in res["contacts"]]
        self.assertEqual(names, ["Eva", "Olle"])
        self.assertTrue(res["contacts"][0]["isPrimary"])
        olle = CrmPerson.objects.get(name="Olle")
        res = self.post(self.url(f"/{olle.id}/primary"), {})
        self.assertEqual([c["name"] for c in res["contacts"]], ["Olle", "Eva"])
        self.deal.refresh_from_db()
        self.assertEqual(self.deal.person_id, olle.id)

    def test_link_existing_and_unlink(self):
        stray = crm.create_person(name="Kalle Växel", phone="040-9")
        found = self.get("/api/admin/crm/people?q=kalle")["rows"]
        self.assertEqual([p["name"] for p in found], ["Kalle Växel"])
        res = self.post(self.url(), {"personId": str(stray.id)})
        self.assertIn("Kalle Växel", [c["name"] for c in res["contacts"]])
        stray.refresh_from_db()
        self.assertEqual(stray.account_id, self.deal.account_id)
        # Ta bort huvudkontakten → nästa kontakt på kontot tar över.
        eva = CrmPerson.objects.get(name="Eva")
        res = self.post(self.url(f"/{eva.id}/unlink"), {})
        self.assertEqual([c["name"] for c in res["contacts"]], ["Kalle Växel"])
        self.assertTrue(res["contacts"][0]["isPrimary"])

    def test_contact_on_deal_without_account_creates_account(self):
        deal = crm.create_deal(name="Weblead utan bolag")
        res = self.post(f"/api/admin/crm/deals/{deal.id}/contacts", {"phone": "070-1"})
        self.assertTrue(res["ok"])
        deal.refresh_from_db()
        self.assertIsNotNone(deal.account_id)
        self.assertEqual(deal.account.name, "Weblead utan bolag")
        self.assertEqual(self.post(f"/api/admin/crm/deals/{deal.id}/contacts", {})["reason"],
                         "contact_required")

    def test_edit_contact(self):
        eva = CrmPerson.objects.get(name="Eva")
        res = self.post(f"/api/admin/crm/people/{eva.id}/update", {
            "name": "Eva Svensson", "email": "EVA@EX.TEST",
        })
        self.assertEqual(res["person"]["name"], "Eva Svensson")
        self.assertEqual(res["person"]["email"], "eva@ex.test")
        self.assertEqual(res["person"]["phone"], "040-1")
