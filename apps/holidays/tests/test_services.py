from datetime import date, timedelta

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.accounts.models import User
from apps.calendar_data.models import BankHoliday
from apps.holidays import services
from apps.holidays.models import HolidayRequest, HolidayRequestDay
from apps.org.models import ChapterLeadAssignment, Cluster, Squad, SquadWatcher, Tribe
from apps.org.titles import seed_default_titles


def _next_weekday(base, target_weekday):
    days_ahead = (target_weekday - base.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return base + timedelta(days=days_ahead)


class HolidayWorkflowTestCase(TestCase):
    def setUp(self):
        today = date.today()
        self.monday = _next_weekday(today, 0)
        self.tuesday = self.monday + timedelta(days=1)
        self.saturday = _next_weekday(today, 5)

        self.tribe = Tribe.objects.create(name="Tribe A")
        self.cluster = Cluster.objects.create(tribe=self.tribe, name="Cluster A")
        self.squad = Squad.objects.create(cluster=self.cluster, name="Squad A")
        self.watcher_email = "watcher@example.com"
        SquadWatcher.objects.create(squad=self.squad, email=self.watcher_email)
        self.titles = seed_default_titles(self.tribe)

        self.scrum_master = User.objects.create_user(
            username="sm1", title=self.titles["scrum_master"], email="sm@example.com"
        )
        self.chapter_lead = User.objects.create_user(
            username="lead1",
            role=User.Role.CHAPTER_LEAD,
            title=self.titles["data_scientist"],
            squad=self.squad,
            email="lead@example.com",
        )
        self.end_user = User.objects.create_user(
            username="eu1",
            role=User.Role.END_USER,
            title=self.titles["data_scientist"],
            squad=self.squad,
            email="eu@example.com",
        )


class ResolveChapterLeadTests(HolidayWorkflowTestCase):
    def test_routes_to_assigned_lead_by_title(self):
        lead = services.resolve_chapter_lead(self.end_user)
        self.assertEqual(lead, self.chapter_lead)

    def test_self_approval_falls_back_to_scrum_master(self):
        # the Chapter Lead's own title routes to themselves - must fall back
        lead = services.resolve_chapter_lead(self.chapter_lead)
        self.assertEqual(lead, self.scrum_master)
        self.assertNotEqual(lead, self.chapter_lead)


class SubmitRequestTests(HolidayWorkflowTestCase):
    def test_submit_creates_pending_request_with_routed_lead(self):
        req = services.submit_request(
            self.end_user, [(self.monday, HolidayRequestDay.DayPart.FULL)]
        )
        self.assertEqual(req.days.get().status, HolidayRequestDay.Status.PENDING)
        self.assertEqual(req.routed_chapter_lead, self.chapter_lead)
        self.assertEqual(req.days.count(), 1)

    def test_mixed_full_and_half_days_in_one_request(self):
        req = services.submit_request(
            self.end_user,
            [(self.monday, HolidayRequestDay.DayPart.FULL), (self.tuesday, HolidayRequestDay.DayPart.HALF)],
        )
        self.assertEqual(req.total_units, 1.5)

    def test_weekend_rejected(self):
        with self.assertRaises(ValidationError):
            services.submit_request(self.end_user, [(self.saturday, HolidayRequestDay.DayPart.FULL)])

    def test_bank_holiday_rejected(self):
        BankHoliday.objects.create(tribe=self.tribe, date=self.monday, name="Test Holiday")
        with self.assertRaises(ValidationError):
            services.submit_request(self.end_user, [(self.monday, HolidayRequestDay.DayPart.FULL)])

    def test_duplicate_dates_in_same_submission_rejected(self):
        with self.assertRaises(ValidationError):
            services.submit_request(
                self.end_user,
                [
                    (self.monday, HolidayRequestDay.DayPart.FULL),
                    (self.monday, HolidayRequestDay.DayPart.HALF),
                ],
            )

    def test_overlap_with_existing_pending_request_rejected(self):
        services.submit_request(self.end_user, [(self.monday, HolidayRequestDay.DayPart.FULL)])
        with self.assertRaises(ValidationError):
            services.submit_request(self.end_user, [(self.monday, HolidayRequestDay.DayPart.HALF)])

    def test_submit_sends_email_to_lead_and_watchers(self):
        mail.outbox.clear()
        # transaction.on_commit callbacks only fire on a real commit; a
        # TestCase test runs inside a rolled-back transaction, so they must
        # be captured and executed explicitly.
        with self.captureOnCommitCallbacks(execute=True):
            services.submit_request(self.end_user, [(self.monday, HolidayRequestDay.DayPart.FULL)])
        recipients = [addr for message in mail.outbox for addr in message.to]
        self.assertIn(self.chapter_lead.email, recipients)
        self.assertIn(self.watcher_email, recipients)


class ApproveRefuseTests(HolidayWorkflowTestCase):
    def setUp(self):
        super().setUp()
        self.req = services.submit_request(self.end_user, [(self.monday, HolidayRequestDay.DayPart.FULL)])
        self.day = self.req.days.get()

    def test_wrong_approver_rejected(self):
        with self.assertRaises(ValidationError):
            services.approve_day(self.day, self.scrum_master)

    def test_approve_sets_status_and_sends_email(self):
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            services.approve_day(self.day, self.chapter_lead)
        self.day.refresh_from_db()
        self.assertEqual(self.day.status, HolidayRequestDay.Status.APPROVED)
        self.assertEqual(self.day.decided_by, self.chapter_lead)
        recipients = [addr for message in mail.outbox for addr in message.to]
        self.assertIn(self.end_user.email, recipients)

    def test_refuse_sets_status_reason_and_sends_email(self):
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            services.refuse_day(self.day, self.chapter_lead, reason="Too many people out that week")
        self.day.refresh_from_db()
        self.assertEqual(self.day.status, HolidayRequestDay.Status.REFUSED)
        self.assertEqual(self.day.decision_reason, "Too many people out that week")
        recipients = [addr for message in mail.outbox for addr in message.to]
        self.assertIn(self.end_user.email, recipients)

    def test_refuse_without_reason_rejected(self):
        with self.assertRaises(ValidationError):
            services.refuse_day(self.day, self.chapter_lead, reason="")
        with self.assertRaises(ValidationError):
            services.refuse_day(self.day, self.chapter_lead, reason="   ")

    def test_cannot_decide_already_decided_day(self):
        services.approve_day(self.day, self.chapter_lead)
        with self.assertRaises(ValidationError):
            services.refuse_day(self.day, self.chapter_lead, reason="Changed my mind")

    def test_multi_day_request_can_be_partially_approved(self):
        req = services.submit_request(
            self.end_user,
            [(self.tuesday, HolidayRequestDay.DayPart.FULL), (self.tuesday + timedelta(days=1), HolidayRequestDay.DayPart.FULL)],
        )
        day1, day2 = req.days.order_by("date")
        services.approve_day(day1, self.chapter_lead)
        services.refuse_day(day2, self.chapter_lead, reason="Team is short-staffed that day")

        day1.refresh_from_db()
        day2.refresh_from_db()
        self.assertEqual(day1.status, HolidayRequestDay.Status.APPROVED)
        self.assertEqual(day2.status, HolidayRequestDay.Status.REFUSED)


class WeekdaySubrangesTests(TestCase):
    def test_two_week_sprint_range_splits_at_the_weekend(self):
        monday = _next_weekday(date.today(), 0)
        end = monday + timedelta(days=11)  # Friday of the following week
        result = services._weekday_subranges(monday, end)
        self.assertEqual(
            result,
            [(monday, monday + timedelta(days=4)), (monday + timedelta(days=7), end)],
        )

    def test_single_week_range_with_no_weekend_is_one_subrange(self):
        monday = _next_weekday(date.today(), 0)
        friday = monday + timedelta(days=4)
        self.assertEqual(services._weekday_subranges(monday, friday), [(monday, friday)])

    def test_pure_weekend_range_yields_nothing(self):
        saturday = _next_weekday(date.today(), 5)
        sunday = saturday + timedelta(days=1)
        self.assertEqual(services._weekday_subranges(saturday, sunday), [])

    def test_no_subrange_ever_contains_a_weekend_day(self):
        monday = _next_weekday(date.today(), 0)
        end = monday + timedelta(days=25)  # spans several weekends
        for sub_start, sub_end in services._weekday_subranges(monday, end):
            day = sub_start
            while day <= sub_end:
                self.assertLess(day.weekday(), 5, f"{day} is a weekend but was included")
                day += timedelta(days=1)


class SprintCalendarFeedTests(HolidayWorkflowTestCase):
    def test_sprint_background_events_never_cover_a_weekend(self):
        from apps.calendar_data.models import Sprint

        monday = _next_weekday(date.today(), 0)
        sprint = Sprint.objects.create(
            tribe=self.tribe,
            year=monday.year,
            quarter=Sprint.Quarter.Q1,
            name="SP1",
            start_date=monday,
            end_date=monday + timedelta(days=11),
        )

        events = services.calendar_feed_events(self.squad, monday - timedelta(days=3), monday + timedelta(days=14))
        sprint_events = [e for e in events if e["id"].startswith(f"sprint-{sprint.pk}-")]

        self.assertEqual(len(sprint_events), 2)  # one per weekday-only week
        for event in sprint_events:
            start = date.fromisoformat(event["start"])
            end = date.fromisoformat(event["end"]) - timedelta(days=1)  # FullCalendar end is exclusive
            day = start
            while day <= end:
                self.assertLess(day.weekday(), 5, f"{day} is a weekend but appeared in a sprint event")
                day += timedelta(days=1)


class BackupChapterLeadTests(HolidayWorkflowTestCase):
    def setUp(self):
        super().setUp()
        self.backup = User.objects.create_user(
            username="backup1",
            role=User.Role.END_USER,  # any role can be a backup
            title=self.titles["business_analyst"],
            squad=self.squad,
            email="backup@example.com",
        )
        ChapterLeadAssignment.objects.create(
            tribe=self.tribe, title=self.titles["data_scientist"], chapter_lead=self.backup
        )
        self.req = services.submit_request(self.end_user, [(self.monday, HolidayRequestDay.DayPart.FULL)])
        self.day = self.req.days.get()

    def test_backup_is_an_approver(self):
        self.assertTrue(services.is_approver(self.backup))

    def test_non_backup_end_user_is_not_an_approver(self):
        self.assertFalse(services.is_approver(self.end_user))

    def test_backup_sees_title_in_approvable_titles(self):
        self.assertIn(self.titles["data_scientist"].pk, services.approvable_title_ids_for(self.backup))

    def test_backup_can_approve_even_though_not_routed_chapter_lead(self):
        self.assertNotEqual(self.req.routed_chapter_lead_id, self.backup.pk)
        services.approve_day(self.day, self.backup)
        self.day.refresh_from_db()
        self.assertEqual(self.day.status, HolidayRequestDay.Status.APPROVED)
        self.assertEqual(self.day.decided_by, self.backup)

    def test_backup_can_refuse_with_reason(self):
        services.refuse_day(self.day, self.backup, reason="Covering while lead1 is away")
        self.day.refresh_from_db()
        self.assertEqual(self.day.status, HolidayRequestDay.Status.REFUSED)

    def test_unrelated_user_still_cannot_decide(self):
        stranger = User.objects.create_user(
            username="stranger", role=User.Role.END_USER, title=self.titles["ai_engineer"], squad=self.squad
        )
        with self.assertRaises(ValidationError):
            services.approve_day(self.day, stranger)


class ResyncPendingRoutingTests(HolidayWorkflowTestCase):
    def test_new_chapter_lead_takes_over_pending_requests(self):
        req = services.submit_request(self.end_user, [(self.monday, HolidayRequestDay.DayPart.FULL)])
        self.assertEqual(req.routed_chapter_lead, self.chapter_lead)

        new_lead = User.objects.create_user(
            username="lead2", role=User.Role.END_USER, title=self.titles["business_analyst"], squad=self.squad
        )
        # Promote lead1 off Data Scientist and lead2 onto it, the way the
        # User admin's save_model would after a role/title change.
        self.chapter_lead.role = User.Role.END_USER
        self.chapter_lead.save()
        new_lead.role = User.Role.CHAPTER_LEAD
        new_lead.title = self.titles["data_scientist"]
        new_lead.save()

        services.resync_pending_routing_for_title(self.titles["data_scientist"].pk)
        req.refresh_from_db()
        self.assertEqual(req.routed_chapter_lead, new_lead)

    def test_decided_days_are_not_rerouted(self):
        req = services.submit_request(self.end_user, [(self.monday, HolidayRequestDay.DayPart.FULL)])
        day = req.days.get()
        services.approve_day(day, self.chapter_lead)

        # data_scientist already had lead1 as primary - reassigning would
        # violate one_chapter_lead_per_title, so demote lead1 first.
        self.chapter_lead.role = User.Role.END_USER
        self.chapter_lead.save()
        User.objects.create_user(
            username="lead2", role=User.Role.CHAPTER_LEAD, title=self.titles["data_scientist"], squad=self.squad
        )

        services.resync_pending_routing_for_title(self.titles["data_scientist"].pk)
        req.refresh_from_db()
        # the request has no pending days left, so it's left alone
        self.assertEqual(req.routed_chapter_lead, self.chapter_lead)

    def test_losing_the_primary_falls_back_to_scrum_master(self):
        req = services.submit_request(self.end_user, [(self.monday, HolidayRequestDay.DayPart.FULL)])
        self.chapter_lead.role = User.Role.END_USER
        self.chapter_lead.save()

        services.resync_pending_routing_for_title(self.titles["data_scientist"].pk)
        req.refresh_from_db()
        self.assertEqual(req.routed_chapter_lead, self.scrum_master)


class SilentlySetDayStatusTests(HolidayWorkflowTestCase):
    """silently_set_day_status lets a SILENT_EDIT_PERM holder directly add
    a full/half day holiday for a squad member, or cancel one of their
    existing ones - restricted to their own squad, never against a Chapter
    Lead, still keeping the routed Chapter Lead informed (recap email +
    normal visibility in their approval inbox) even though no approval
    step happens."""

    def setUp(self):
        super().setUp()
        self.editor = User.objects.create_user(
            username="editor1",
            role=User.Role.END_USER,
            title=self.titles["ai_engineer"],
            squad=self.squad,
            email="editor@example.com",
        )

    def test_editor_outside_the_members_squad_rejected(self):
        other_squad = Squad.objects.create(cluster=self.cluster, name="Squad B")
        outsider = User.objects.create_user(
            username="outsider",
            role=User.Role.END_USER,
            title=self.titles["ai_engineer"],
            squad=other_squad,
            email="outsider@example.com",
        )
        with self.assertRaises(ValidationError):
            services.silently_set_day_status(
                outsider, self.end_user, [(self.monday, "add", "full")], comment="test"
            )

    def test_editor_with_no_squad_rejected(self):
        homeless_admin = User.objects.create_user(username="admin2", title=self.titles["scrum_master"])
        with self.assertRaises(ValidationError):
            services.silently_set_day_status(
                homeless_admin, self.end_user, [(self.monday, "add", "full")], comment="test"
            )

    def test_chapter_lead_can_never_be_targeted(self):
        with self.assertRaises(ValidationError):
            services.silently_set_day_status(
                self.editor, self.chapter_lead, [(self.monday, "add", "full")], comment="test"
            )

    def test_comment_required(self):
        with self.assertRaises(ValidationError):
            services.silently_set_day_status(
                self.editor, self.end_user, [(self.monday, "add", "full")], comment="   "
            )

    def test_weekend_rejected_for_add(self):
        with self.assertRaises(ValidationError):
            services.silently_set_day_status(
                self.editor, self.end_user, [(self.saturday, "add", "full")], comment="Emergency"
            )

    def test_bank_holiday_rejected_for_add(self):
        BankHoliday.objects.create(tribe=self.tribe, date=self.monday, name="Test Holiday")
        with self.assertRaises(ValidationError):
            services.silently_set_day_status(
                self.editor, self.end_user, [(self.monday, "add", "full")], comment="Emergency"
            )

    def test_add_new_date_creates_an_approved_day(self):
        days = services.silently_set_day_status(
            self.editor, self.end_user, [(self.monday, "add", "full")], comment="Confirmed by phone"
        )
        self.assertEqual(len(days), 1)
        day = days[0]
        self.assertEqual(day.status, HolidayRequestDay.Status.APPROVED)
        self.assertEqual(day.decided_by, self.editor)
        self.assertEqual(day.decision_reason, "Confirmed by phone")
        self.assertEqual(day.request.requester, self.end_user)
        self.assertEqual(day.request.routed_chapter_lead, self.chapter_lead)

    def test_add_on_existing_pending_day_updates_it_in_place(self):
        req = services.submit_request(self.end_user, [(self.monday, HolidayRequestDay.DayPart.FULL)])
        pending_day = req.days.get()

        services.silently_set_day_status(
            self.editor, self.end_user, [(self.monday, "add", "half")], comment="Changed after discussion"
        )

        pending_day.refresh_from_db()
        self.assertEqual(pending_day.status, HolidayRequestDay.Status.APPROVED)
        self.assertEqual(pending_day.day_part, HolidayRequestDay.DayPart.HALF)
        self.assertEqual(pending_day.decided_by, self.editor)
        self.assertEqual(
            HolidayRequestDay.objects.filter(request__requester=self.end_user, date=self.monday).count(), 1
        )

    def test_cancel_without_an_existing_holiday_rejected(self):
        with self.assertRaises(ValidationError):
            services.silently_set_day_status(
                self.editor, self.end_user, [(self.monday, "cancel", "full")], comment="Never mind"
            )

    def test_cancel_marks_an_existing_approved_day_cancelled(self):
        services.silently_set_day_status(
            self.editor, self.end_user, [(self.monday, "add", "full")], comment="Confirmed by phone"
        )
        services.silently_set_day_status(
            self.editor, self.end_user, [(self.monday, "cancel", "full")], comment="No longer needed"
        )
        day = HolidayRequestDay.objects.get(request__requester=self.end_user, date=self.monday)
        self.assertEqual(day.status, HolidayRequestDay.Status.CANCELLED)
        self.assertEqual(day.decision_reason, "No longer needed")

    def test_cancelled_day_excluded_from_calendar_feed(self):
        services.silently_set_day_status(
            self.editor, self.end_user, [(self.monday, "add", "full")], comment="Confirmed by phone"
        )
        services.silently_set_day_status(
            self.editor, self.end_user, [(self.monday, "cancel", "full")], comment="No longer needed"
        )
        events = services.calendar_feed_events(self.squad, self.monday, self.monday)
        holiday_events = [e for e in events if e.get("extendedProps", {}).get("type") == "holiday"]
        self.assertEqual(holiday_events, [])

    def test_sends_recap_email_to_chapter_lead(self):
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            services.silently_set_day_status(
                self.editor, self.end_user, [(self.monday, "add", "full")], comment="Confirmed by phone"
            )
        recipients = [addr for message in mail.outbox for addr in message.to]
        self.assertIn(self.chapter_lead.email, recipients)
        self.assertIn(self.editor.username, mail.outbox[0].body)
        self.assertIn("Confirmed by phone", mail.outbox[0].body)
