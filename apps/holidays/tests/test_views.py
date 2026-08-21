import json
from datetime import date, timedelta

from django.contrib.auth.models import Permission
from django.core import mail
from django.test import TestCase

from apps.accounts.models import User
from apps.calendar_data.models import BankHoliday
from apps.holidays.models import HolidayRequest, HolidayRequestDay
from apps.org.models import ChapterLeadAssignment, Cluster, Squad, SquadWatcher, Tribe
from apps.org.titles import seed_default_titles


def _next_monday(base):
    days_ahead = (0 - base.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return base + timedelta(days=days_ahead)


class HolidayViewsTestCase(TestCase):
    def setUp(self):
        self.monday = _next_monday(date.today())

        tribe = Tribe.objects.create(name="Tribe A")
        cluster = Cluster.objects.create(tribe=tribe, name="Cluster A")
        self.squad = Squad.objects.create(cluster=cluster, name="Squad A")
        self.other_squad = Squad.objects.create(cluster=cluster, name="Squad B")
        SquadWatcher.objects.create(squad=self.squad, email="watcher@example.com")
        self.titles = seed_default_titles(tribe)

        self.chapter_lead = User.objects.create_user(
            username="lead1",
            password="pass1234",
            role=User.Role.CHAPTER_LEAD,
            title=self.titles["data_scientist"],
            squad=self.squad,
            email="lead@example.com",
        )
        ChapterLeadAssignment.objects.create(
            tribe=tribe, title=self.titles["data_scientist"], chapter_lead=self.chapter_lead
        )
        self.end_user = User.objects.create_user(
            username="eu1",
            password="pass1234",
            role=User.Role.END_USER,
            title=self.titles["data_scientist"],
            squad=self.squad,
            email="eu@example.com",
        )


class ApprovalInboxAccessTests(HolidayViewsTestCase):
    def test_anonymous_redirected_to_login(self):
        response = self.client.get("/approvals/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_end_user_forbidden(self):
        self.client.login(username="eu1", password="pass1234")
        response = self.client.get("/approvals/")
        self.assertEqual(response.status_code, 403)

    def test_chapter_lead_allowed(self):
        self.client.login(username="lead1", password="pass1234")
        response = self.client.get("/approvals/")
        self.assertEqual(response.status_code, 200)


class SubmitRequestViewTests(HolidayViewsTestCase):
    def test_cannot_submit_for_another_squad(self):
        self.client.login(username="eu1", password="pass1234")
        response = self.client.post(
            f"/squads/{self.other_squad.id}/requests/submit/",
            {"days_json": json.dumps([{"date": self.monday.isoformat(), "day_part": "full"}])},
        )
        self.assertEqual(response.status_code, 403)

    def test_submit_creates_request_and_redirects(self):
        self.client.login(username="eu1", password="pass1234")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/squads/{self.squad.id}/requests/submit/",
                {"days_json": json.dumps([{"date": self.monday.isoformat(), "day_part": "full"}])},
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(HolidayRequest.objects.filter(requester=self.end_user).count(), 1)

    def test_invalid_submission_shows_error_and_does_not_create(self):
        self.client.login(username="eu1", password="pass1234")
        saturday = self.monday + timedelta(days=5)
        self.client.post(
            f"/squads/{self.squad.id}/requests/submit/",
            {"days_json": json.dumps([{"date": saturday.isoformat(), "day_part": "full"}])},
        )
        self.assertEqual(HolidayRequest.objects.filter(requester=self.end_user).count(), 0)


class FullWorkflowIntegrationTests(HolidayViewsTestCase):
    def test_submit_then_approve_end_to_end(self):
        self.client.login(username="eu1", password="pass1234")
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/squads/{self.squad.id}/requests/submit/",
                {"days_json": json.dumps([{"date": self.monday.isoformat(), "day_part": "full"}])},
            )
        submitted_recipients = [addr for m in mail.outbox for addr in m.to]
        self.assertIn(self.chapter_lead.email, submitted_recipients)
        self.assertIn("watcher@example.com", submitted_recipients)

        req = HolidayRequest.objects.get(requester=self.end_user)
        day = req.days.get()
        self.assertEqual(day.status, HolidayRequestDay.Status.PENDING)

        self.client.logout()
        self.client.login(username="lead1", password="pass1234")
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"/approvals/days/{day.id}/approve/")
        self.assertEqual(response.status_code, 302)

        day.refresh_from_db()
        self.assertEqual(day.status, HolidayRequestDay.Status.APPROVED)
        decision_recipients = [addr for m in mail.outbox for addr in m.to]
        self.assertIn(self.end_user.email, decision_recipients)

    def test_refuse_requires_a_justification(self):
        self.client.login(username="eu1", password="pass1234")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/squads/{self.squad.id}/requests/submit/",
                {"days_json": json.dumps([{"date": self.monday.isoformat(), "day_part": "full"}])},
            )
        day = HolidayRequestDay.objects.get(request__requester=self.end_user)

        self.client.logout()
        self.client.login(username="lead1", password="pass1234")
        response = self.client.post(f"/approvals/days/{day.id}/refuse/", {"reason": ""})
        self.assertEqual(response.status_code, 302)

        day.refresh_from_db()
        self.assertEqual(day.status, HolidayRequestDay.Status.PENDING)  # unchanged - reason was required

    def test_multi_day_request_partial_decision_via_views(self):
        self.client.login(username="eu1", password="pass1234")
        tuesday = self.monday + timedelta(days=1)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/squads/{self.squad.id}/requests/submit/",
                {
                    "days_json": json.dumps(
                        [
                            {"date": self.monday.isoformat(), "day_part": "full"},
                            {"date": tuesday.isoformat(), "day_part": "full"},
                        ]
                    )
                },
            )
        day1, day2 = HolidayRequestDay.objects.filter(request__requester=self.end_user).order_by("date")

        self.client.logout()
        self.client.login(username="lead1", password="pass1234")
        self.client.post(f"/approvals/days/{day1.id}/approve/")
        self.client.post(f"/approvals/days/{day2.id}/refuse/", {"reason": "Coverage conflict"})

        day1.refresh_from_db()
        day2.refresh_from_db()
        self.assertEqual(day1.status, HolidayRequestDay.Status.APPROVED)
        self.assertEqual(day2.status, HolidayRequestDay.Status.REFUSED)
        self.assertEqual(day2.decision_reason, "Coverage conflict")


class ApprovalInboxFilterTests(HolidayViewsTestCase):
    def setUp(self):
        super().setUp()
        self.other_end_user = User.objects.create_user(
            username="eu2",
            password="pass1234",
            role=User.Role.END_USER,
            title=self.titles["data_scientist"],
            squad=self.squad,
            email="eu2@example.com",
        )
        tuesday = self.monday + timedelta(days=1)
        with self.captureOnCommitCallbacks(execute=True):
            from apps.holidays import services

            services.submit_request(self.end_user, [(self.monday, "full")])
            services.submit_request(self.other_end_user, [(tuesday, "full")])

    def test_pending_dropdown_filters_by_requester(self):
        day1 = HolidayRequestDay.objects.get(request__requester=self.end_user)
        day2 = HolidayRequestDay.objects.get(request__requester=self.other_end_user)

        self.client.login(username="lead1", password="pass1234")
        response = self.client.get(f"/approvals/?pending_requester={self.end_user.pk}")
        # The filter dropdown itself always lists both requesters as
        # options, so check the actual per-day action URLs (only rendered
        # for rows in the table) rather than raw username substrings.
        self.assertContains(response, f"/approvals/days/{day1.id}/approve/")
        self.assertNotContains(response, f"/approvals/days/{day2.id}/approve/")

    def test_decided_dropdown_filters_by_requester(self):
        from apps.holidays import services

        day1 = HolidayRequestDay.objects.get(request__requester=self.end_user)  # dated self.monday
        day2 = HolidayRequestDay.objects.get(request__requester=self.other_end_user)  # dated tuesday
        lead = self.chapter_lead
        with self.captureOnCommitCallbacks(execute=True):
            services.approve_day(day1, lead)
            services.approve_day(day2, lead)

        self.client.login(username="lead1", password="pass1234")
        response = self.client.get(f"/approvals/?decided_requester={self.other_end_user.pk}")
        content = response.content.decode()
        # The filter dropdown (which precedes the table) lists both
        # usernames as options regardless of which is selected, so scope
        # the check to the <table> itself, past the dropdown markup.
        decided_table = content.split("Recently decided")[1].split("<table>")[1]
        self.assertIn("eu2", decided_table)
        self.assertNotIn("eu1", decided_table)


class TemplateRenderingSmokeTests(HolidayViewsTestCase):
    """GETs that fully render templates (including the FullCalendar embed
    and dict-by-quarter-key metrics table), catching template syntax errors
    that a redirect-only assertion would miss."""

    def test_squad_calendar_page_renders(self):
        self.client.login(username="eu1", password="pass1234")
        response = self.client.get(f"/squads/{self.squad.id}/calendar/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Request holidays")

    def test_approval_inbox_renders(self):
        self.client.login(username="lead1", password="pass1234")
        response = self.client.get("/approvals/")
        self.assertEqual(response.status_code, 200)

    def test_squad_dashboard_renders(self):
        self.client.login(username="eu1", password="pass1234")
        response = self.client.get(f"/dashboard/squads/{self.squad.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.end_user.title.name)

    def test_cluster_dashboard_renders(self):
        self.client.login(username="lead1", password="pass1234")
        response = self.client.get(f"/dashboard/clusters/{self.squad.cluster_id}/")
        self.assertEqual(response.status_code, 200)


class CrossClusterVisibilityAndNavTests(HolidayViewsTestCase):
    """An End User can view (but not submit for) any squad's calendar
    across the whole tribe, reachable via the cluster/squad picker - not
    just squads in their own cluster."""

    def setUp(self):
        super().setUp()
        other_cluster = Cluster.objects.create(tribe=self.squad.tribe, name="Cluster Z")
        self.far_squad = Squad.objects.create(cluster=other_cluster, name="Squad Far")

    def test_end_user_can_view_squad_calendar_in_another_cluster(self):
        self.client.login(username="eu1", password="pass1234")
        response = self.client.get(f"/squads/{self.far_squad.id}/calendar/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Request holidays")  # not their own squad

    def test_end_user_cannot_submit_for_squad_in_another_cluster(self):
        self.client.login(username="eu1", password="pass1234")
        response = self.client.post(
            f"/squads/{self.far_squad.id}/requests/submit/", {"days_json": "[]"}
        )
        self.assertEqual(response.status_code, 403)

    def test_calendar_picker_lists_squads_from_every_cluster(self):
        self.client.login(username="eu1", password="pass1234")
        response = self.client.get(f"/squads/{self.squad.id}/calendar/")
        self.assertContains(response, "Cluster Z")
        self.assertContains(response, "Squad Far")

    def test_every_squad_option_carries_the_data_attributes_the_picker_needs(self):
        # cluster_squad_picker.js filters squad options by data-cluster and
        # navigates using data-url; without both on every option, switching
        # cluster silently leaves the page on the previous squad.
        self.client.login(username="eu1", password="pass1234")
        response = self.client.get(f"/squads/{self.squad.id}/calendar/")
        for squad in [self.squad, self.other_squad, self.far_squad]:
            self.assertContains(
                response,
                f'data-cluster="{squad.cluster_id}" data-url="/squads/{squad.id}/calendar/"',
            )

    def test_nav_has_no_home_link_and_uses_unprefixed_labels(self):
        self.client.login(username="eu1", password="pass1234")
        response = self.client.get(f"/squads/{self.squad.id}/calendar/")
        header = response.content.decode()
        self.assertNotIn(">Home<", header)
        self.assertIn("Squad calendar", header)
        self.assertIn("Squad metrics", header)
        self.assertNotIn("My squad calendar", header)
        self.assertNotIn("My squad metrics", header)


class CalendarFeedTests(HolidayViewsTestCase):
    def test_feed_filters_by_date_range(self):
        far_future = self.monday + timedelta(days=400)
        BankHoliday.objects.create(tribe=self.squad.tribe, date=self.monday, name="In range")
        BankHoliday.objects.create(tribe=self.squad.tribe, date=far_future, name="Out of range")

        self.client.login(username="eu1", password="pass1234")
        start = (self.monday - timedelta(days=1)).isoformat()
        end = (self.monday + timedelta(days=1)).isoformat()
        response = self.client.get(f"/squads/{self.squad.id}/calendar-feed/?start={start}&end={end}")
        self.assertEqual(response.status_code, 200)
        titles = [event["title"] for event in response.json()]
        self.assertIn("In range", titles)
        self.assertNotIn("Out of range", titles)

    def test_holiday_event_carries_day_part_and_title_for_working_count(self):
        from apps.holidays import services

        with self.captureOnCommitCallbacks(execute=True):
            services.submit_request(self.end_user, [(self.monday, "half")])

        self.client.login(username="eu1", password="pass1234")
        start = (self.monday - timedelta(days=1)).isoformat()
        end = (self.monday + timedelta(days=1)).isoformat()
        response = self.client.get(f"/squads/{self.squad.id}/calendar-feed/?start={start}&end={end}")
        holiday_events = [e for e in response.json() if e.get("extendedProps", {}).get("type") == "holiday"]
        self.assertEqual(len(holiday_events), 1)
        self.assertEqual(holiday_events[0]["extendedProps"]["dayPart"], "half")
        self.assertEqual(holiday_events[0]["extendedProps"]["titleCode"], self.end_user.title_id)


class BackupApproverViewTests(HolidayViewsTestCase):
    """A backup approver doesn't need role=Chapter Lead - being listed as a
    backup for a title is enough to reach the approval inbox and decide
    requests for that title."""

    def setUp(self):
        super().setUp()
        self.backup = User.objects.create_user(
            username="backup1",
            password="pass1234",
            role=User.Role.END_USER,
            title=self.titles["data_scientist"],
            squad=self.squad,
            email="backup@example.com",
        )
        ChapterLeadAssignment.objects.create(
            tribe=self.squad.tribe, title=self.titles["data_scientist"], chapter_lead=self.backup
        )

    def test_backup_can_reach_approval_inbox(self):
        self.client.login(username="backup1", password="pass1234")
        response = self.client.get("/approvals/")
        self.assertEqual(response.status_code, 200)

    def test_backup_sees_approval_inbox_nav_link(self):
        self.client.login(username="backup1", password="pass1234")
        response = self.client.get(f"/squads/{self.squad.id}/calendar/")
        self.assertContains(response, "Approval inbox")

    def test_backup_can_approve_a_day(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.login(username="eu1", password="pass1234")
            self.client.post(
                f"/squads/{self.squad.id}/requests/submit/",
                {"days_json": json.dumps([{"date": self.monday.isoformat(), "day_part": "full"}])},
            )
        day = HolidayRequestDay.objects.get(request__requester=self.end_user)

        self.client.logout()
        self.client.login(username="backup1", password="pass1234")
        response = self.client.post(f"/approvals/days/{day.id}/approve/")
        self.assertEqual(response.status_code, 302)
        day.refresh_from_db()
        self.assertEqual(day.status, HolidayRequestDay.Status.APPROVED)

    def test_plain_end_user_still_gets_403(self):
        plain_user = User.objects.create_user(
            username="eu3",
            password="pass1234",
            role=User.Role.END_USER,
            title=self.titles["business_analyst"],
            squad=self.squad,
        )
        self.client.login(username="eu3", password="pass1234")
        response = self.client.get("/approvals/")
        self.assertEqual(response.status_code, 403)


class SilentEditStatusViewTests(HolidayViewsTestCase):
    """A SILENT_EDIT_PERM holder can directly set a squad member's day
    status from their own squad's calendar - restricted to that squad, and
    visible on the squad_calendar page only there."""

    def setUp(self):
        super().setUp()
        self.editor = User.objects.create_user(
            username="editor1",
            password="pass1234",
            role=User.Role.END_USER,
            title=self.titles["ai_engineer"],
            squad=self.squad,
            email="editor@example.com",
        )
        perm = Permission.objects.get(content_type__app_label="holidays", codename="edit_any_holiday_silently")
        self.editor.user_permissions.add(perm)
        self.editor.is_staff = True  # normally synced by UserAdmin.save_model when granting the perm
        self.editor.save()

    def _post_edit(self, member_id, action="add", day_part="full", comment="Confirmed by phone", squad=None):
        squad = squad or self.squad
        return self.client.post(
            f"/squads/{squad.id}/silent-edit/",
            {
                "member_id": member_id,
                "days_json": json.dumps([{"date": self.monday.isoformat(), "action": action, "day_part": day_part}]),
                "comment": comment,
            },
        )

    def test_panel_visible_on_own_squad_calendar(self):
        self.client.login(username="editor1", password="pass1234")
        response = self.client.get(f"/squads/{self.squad.id}/calendar/")
        self.assertContains(response, "update a member's holiday")

    def test_panel_hidden_on_other_squads_calendar(self):
        self.client.login(username="editor1", password="pass1234")
        response = self.client.get(f"/squads/{self.other_squad.id}/calendar/")
        self.assertNotContains(response, "update a member's holiday")

    def test_panel_hidden_without_the_permission(self):
        self.client.login(username="eu1", password="pass1234")
        response = self.client.get(f"/squads/{self.squad.id}/calendar/")
        self.assertNotContains(response, "update a member's holiday")

    def test_chapter_lead_not_offered_as_a_target(self):
        self.client.login(username="editor1", password="pass1234")
        response = self.client.get(f"/squads/{self.squad.id}/calendar/")
        self.assertNotContains(response, '<option value="{}">'.format(self.chapter_lead.pk))

    def test_editor_can_add_a_holiday_directly(self):
        self.client.login(username="editor1", password="pass1234")
        response = self._post_edit(self.end_user.pk)
        self.assertEqual(response.status_code, 302)
        day = HolidayRequestDay.objects.get(request__requester=self.end_user, date=self.monday)
        self.assertEqual(day.status, HolidayRequestDay.Status.APPROVED)
        self.assertEqual(day.decided_by, self.editor)
        self.assertEqual(day.decision_reason, "Confirmed by phone")

    def test_editor_can_cancel_an_existing_holiday(self):
        self.client.login(username="editor1", password="pass1234")
        self._post_edit(self.end_user.pk, action="add")
        response = self._post_edit(self.end_user.pk, action="cancel", comment="No longer needed")
        self.assertEqual(response.status_code, 302)
        day = HolidayRequestDay.objects.get(request__requester=self.end_user, date=self.monday)
        self.assertEqual(day.status, HolidayRequestDay.Status.CANCELLED)

    def test_editor_cannot_target_the_chapter_lead(self):
        self.client.login(username="editor1", password="pass1234")
        response = self._post_edit(self.chapter_lead.pk)
        self.assertEqual(response.status_code, 302)  # redirects back with an error message, doesn't 500
        self.assertFalse(
            HolidayRequestDay.objects.filter(request__requester=self.chapter_lead, date=self.monday).exists()
        )

    def test_plain_end_user_without_permission_gets_403(self):
        self.client.login(username="eu1", password="pass1234")
        response = self._post_edit(self.end_user.pk)
        self.assertEqual(response.status_code, 403)

    def test_editor_cannot_edit_another_squad(self):
        outsider = User.objects.create_user(
            username="outsider",
            password="pass1234",
            role=User.Role.END_USER,
            title=self.titles["data_scientist"],
            squad=self.other_squad,
            email="outsider@example.com",
        )
        self.client.login(username="editor1", password="pass1234")
        response = self._post_edit(outsider.pk, squad=self.other_squad)
        self.assertEqual(response.status_code, 403)

    def test_recap_email_sent_to_chapter_lead(self):
        mail.outbox.clear()
        self.client.login(username="editor1", password="pass1234")
        with self.captureOnCommitCallbacks(execute=True):
            self._post_edit(self.end_user.pk)
        recipients = [addr for message in mail.outbox for addr in message.to]
        self.assertIn(self.chapter_lead.email, recipients)

    def test_appears_in_chapter_leads_approval_inbox(self):
        self.client.login(username="editor1", password="pass1234")
        self._post_edit(self.end_user.pk, action="add", comment="Called in sick")

        self.client.logout()
        self.client.login(username="lead1", password="pass1234")
        response = self.client.get("/approvals/")
        self.assertContains(response, "Called in sick")
        self.assertContains(response, "editor1")
