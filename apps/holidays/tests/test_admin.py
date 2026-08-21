from datetime import date, timedelta

from django.contrib.auth.models import Permission
from django.test import TestCase

from apps.accounts.models import User
from apps.holidays.models import HolidayRequest, HolidayRequestDay
from apps.org.models import Cluster, Squad, Tribe
from apps.org.titles import seed_default_titles


class SilentEditPermissionAdminAccessTests(TestCase):
    """Direct admin CRUD on HolidayRequest is gated on the
    edit_any_holiday_silently permission, independent of role - a plain
    Scrum Master (without the permission) stays read-only, matching the
    original "writes must go through the workflow views" design; a holder
    of the permission (any role) gets full access."""

    def setUp(self):
        tribe = Tribe.objects.create(name="Tribe A")
        cluster = Cluster.objects.create(tribe=tribe, name="Cluster A")
        self.squad = Squad.objects.create(cluster=cluster, name="Squad A")
        self.titles = seed_default_titles(tribe)

        self.scrum_master = User.objects.create_user(
            username="sm1", password="pass1234", title=self.titles["scrum_master"]
        )
        self.requester = User.objects.create_user(
            username="eu1", role=User.Role.END_USER, title=self.titles["data_scientist"], squad=self.squad
        )
        self.holiday_request = HolidayRequest.objects.create(requester=self.requester)
        self.holiday_request_day = HolidayRequestDay.objects.create(
            request=self.holiday_request, date=date.today() + timedelta(days=10), day_part="full"
        )

        self.editor = User.objects.create_user(
            username="editor1",
            password="pass1234",
            role=User.Role.END_USER,
            title=self.titles["data_scientist"],
            squad=self.squad,
        )
        perm = Permission.objects.get(content_type__app_label="holidays", codename="edit_any_holiday_silently")
        self.editor.user_permissions.add(perm)
        self.editor.is_staff = True  # normally set by UserAdmin.save_model when granting the perm
        self.editor.save()

    def test_scrum_master_without_permission_is_read_only(self):
        self.client.login(username="sm1", password="pass1234")
        response = self.client.get(f"/admin/holidays/holidayrequest/{self.holiday_request.id}/change/")
        self.assertEqual(response.status_code, 200)  # can view
        response = self.client.post(
            f"/admin/holidays/holidayrequest/{self.holiday_request.id}/delete/", {"post": "yes"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(HolidayRequest.objects.filter(pk=self.holiday_request.pk).exists())

    def test_permission_holder_can_edit_directly(self):
        self.client.login(username="editor1", password="pass1234")
        response = self.client.post(
            f"/admin/holidays/holidayrequest/{self.holiday_request.id}/change/",
            {
                "requester": self.requester.pk,
                "routed_chapter_lead": self.scrum_master.pk,
                "note": "",
                "days-TOTAL_FORMS": "1",
                "days-INITIAL_FORMS": "1",
                "days-MIN_NUM_FORMS": "0",
                "days-MAX_NUM_FORMS": "1000",
                "days-0-id": self.holiday_request_day.id,
                "days-0-request": self.holiday_request.id,
                "days-0-date": self.holiday_request_day.date.isoformat(),
                "days-0-day_part": "full",
                "days-0-status": HolidayRequestDay.Status.APPROVED,
                "days-0-decision_reason": "",
            },
        )
        self.holiday_request_day.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.holiday_request_day.status, HolidayRequestDay.Status.APPROVED)

    def test_permission_holder_can_delete_without_any_email(self):
        from django.core import mail

        mail.outbox.clear()
        self.client.login(username="editor1", password="pass1234")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/admin/holidays/holidayrequest/{self.holiday_request.id}/delete/", {"post": "yes"}
            )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(HolidayRequest.objects.filter(pk=self.holiday_request.pk).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_plain_end_user_without_permission_cannot_reach_admin_at_all(self):
        plain_user = User.objects.create_user(
            username="eu2",
            password="pass1234",
            role=User.Role.END_USER,
            title=self.titles["data_scientist"],
            squad=self.squad,
        )
        self.client.login(username="eu2", password="pass1234")
        response = self.client.get(f"/admin/holidays/holidayrequest/{self.holiday_request.id}/change/")
        self.assertNotEqual(response.status_code, 200)
