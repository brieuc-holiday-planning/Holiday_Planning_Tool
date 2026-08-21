from django.test import TestCase

from apps.accounts.models import User
from apps.org.models import Cluster, Squad, Tribe
from apps.org.titles import seed_default_titles


class AdminAccessTests(TestCase):
    def setUp(self):
        tribe = Tribe.objects.create(name="Tribe A")
        cluster = Cluster.objects.create(tribe=tribe, name="Cluster A")
        self.squad = Squad.objects.create(cluster=cluster, name="Squad A")
        self.titles = seed_default_titles(tribe)

        self.scrum_master = User.objects.create_user(
            username="sm1", password="pass1234", title=self.titles["scrum_master"]
        )
        self.chapter_lead = User.objects.create_user(
            username="lead1",
            password="pass1234",
            role=User.Role.CHAPTER_LEAD,
            title=self.titles["data_scientist"],
            squad=self.squad,
        )
        self.end_user = User.objects.create_user(
            username="eu1",
            password="pass1234",
            role=User.Role.END_USER,
            title=self.titles["data_scientist"],
            squad=self.squad,
        )

    def test_scrum_master_is_staff_automatically(self):
        self.assertTrue(self.scrum_master.is_staff)
        self.assertFalse(self.scrum_master.is_superuser)

    def test_chapter_lead_and_end_user_are_not_staff(self):
        self.assertFalse(self.chapter_lead.is_staff)
        self.assertFalse(self.end_user.is_staff)

    def test_scrum_master_can_reach_admin_index(self):
        self.client.login(username="sm1", password="pass1234")
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)

    def test_scrum_master_can_manage_squads(self):
        self.client.login(username="sm1", password="pass1234")
        response = self.client.get("/admin/org/squad/")
        self.assertEqual(response.status_code, 200)
        response = self.client.get("/admin/org/squad/add/")
        self.assertEqual(response.status_code, 200)

    def test_end_user_redirected_away_from_admin(self):
        self.client.login(username="eu1", password="pass1234")
        response = self.client.get("/admin/", follow=False)
        self.assertNotEqual(response.status_code, 200)

    def test_chapter_lead_redirected_away_from_admin(self):
        self.client.login(username="lead1", password="pass1234")
        response = self.client.get("/admin/", follow=False)
        self.assertNotEqual(response.status_code, 200)

    def test_holiday_requests_are_read_only_in_admin(self):
        self.client.login(username="sm1", password="pass1234")
        response = self.client.get("/admin/holidays/holidayrequest/add/")
        self.assertEqual(response.status_code, 403)


class SilentHolidayEditPermissionToggleTests(AdminAccessTests):
    """A Scrum Master can grant/revoke the "silently edit any holiday
    request" permission on the User admin form, and it correctly keeps
    is_staff in sync (needed for a non-Scrum-Master grantee to even reach
    /admin/) in both directions."""

    def _change_form_payload(self, **overrides):
        payload = {
            "username": "eu1",
            "first_name": "",
            "last_name": "",
            "email": "",
            "role": User.Role.END_USER,
            "title": self.titles["data_scientist"].pk,
            "squad": self.squad.pk,
            "is_active": "on",
            "_save": "Save",
        }
        payload.update(overrides)
        return payload

    def test_granting_permission_syncs_is_staff(self):
        self.client.login(username="sm1", password="pass1234")
        url = f"/admin/accounts/user/{self.end_user.pk}/change/"

        response = self.client.post(url, self._change_form_payload(can_edit_holidays_silently="on"))
        self.assertEqual(response.status_code, 302)

        updated = User.objects.get(pk=self.end_user.pk)
        self.assertTrue(updated.has_perm("holidays.edit_any_holiday_silently"))
        self.assertTrue(updated.is_staff)

    def test_revoking_permission_syncs_is_staff_back_off(self):
        self.client.login(username="sm1", password="pass1234")
        url = f"/admin/accounts/user/{self.end_user.pk}/change/"

        self.client.post(url, self._change_form_payload(can_edit_holidays_silently="on"))
        response = self.client.post(url, self._change_form_payload())  # checkbox omitted = unchecked
        self.assertEqual(response.status_code, 302)

        updated = User.objects.get(pk=self.end_user.pk)
        self.assertFalse(updated.has_perm("holidays.edit_any_holiday_silently"))
        self.assertFalse(updated.is_staff)

    def test_end_user_gains_admin_access_once_granted(self):
        self.client.login(username="sm1", password="pass1234")
        url = f"/admin/accounts/user/{self.end_user.pk}/change/"
        self.client.post(url, self._change_form_payload(can_edit_holidays_silently="on"))

        self.client.logout()
        self.client.login(username="eu1", password="pass1234")
        response = self.client.get("/admin/holidays/holidayrequest/")
        self.assertEqual(response.status_code, 200)


class UserAdminChapterLeadResyncTests(AdminAccessTests):
    """Assigning role=Chapter Lead + a title on the User admin *is* how
    someone becomes the validator for that title - in-flight requests
    should follow the reassignment, not stay pinned to the old lead."""

    def _change_form_payload(self, username, title_pk, squad_pk, role):
        return {
            "username": username,
            "first_name": "",
            "last_name": "",
            "email": "",
            "role": role,
            "title": title_pk,
            "squad": squad_pk,
            "is_active": "on",
            "_save": "Save",
        }

    def test_promoting_a_new_chapter_lead_reroutes_pending_requests(self):
        from datetime import date, timedelta

        from apps.holidays import services

        def next_monday(base):
            days_ahead = (0 - base.weekday()) % 7 or 7
            return base + timedelta(days=days_ahead)

        req = services.submit_request(self.end_user, [(next_monday(date.today()), "full")])
        self.assertEqual(req.routed_chapter_lead, self.chapter_lead)

        new_lead = User.objects.create_user(
            username="lead2",
            password="pass1234",
            role=User.Role.END_USER,
            title=self.titles["business_analyst"],
            squad=self.squad,
        )

        self.client.login(username="sm1", password="pass1234")
        # Demote lead1 off Data Scientist first, freeing up the title.
        self.client.post(
            f"/admin/accounts/user/{self.chapter_lead.pk}/change/",
            self._change_form_payload(
                "lead1", self.titles["data_scientist"].pk, self.squad.pk, User.Role.END_USER
            ),
        )
        # Promote lead2 onto Data Scientist.
        self.client.post(
            f"/admin/accounts/user/{new_lead.pk}/change/",
            self._change_form_payload(
                "lead2", self.titles["data_scientist"].pk, self.squad.pk, User.Role.CHAPTER_LEAD
            ),
        )

        req.refresh_from_db()
        self.assertEqual(req.routed_chapter_lead, new_lead)
