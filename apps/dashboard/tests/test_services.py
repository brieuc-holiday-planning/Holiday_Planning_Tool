from datetime import date, timedelta

from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.calendar_data.models import BankHoliday
from apps.dashboard import services
from apps.holidays.models import HolidayRequest, HolidayRequestDay
from apps.org.models import Cluster, Squad, Tribe
from apps.org.titles import seed_default_titles


def _independent_weekday_count(year, quarter):
    """Recomputed from scratch (not calling the implementation under test)
    so this is a real check, not a tautology."""
    start_month = (quarter - 1) * 3 + 1
    day = date(year, start_month, 1)
    end_month = start_month + 3
    end = date(year, end_month, 1) if end_month <= 12 else date(year + 1, 1, 1)
    count = 0
    while day < end:
        if day.weekday() < 5:
            count += 1
        day += timedelta(days=1)
    return count


class DashboardMetricsTests(TestCase):
    def setUp(self):
        self.year = 2026
        self.tribe = Tribe.objects.create(name="Tribe A")
        self.cluster = Cluster.objects.create(tribe=self.tribe, name="Cluster A")
        self.squad = Squad.objects.create(cluster=self.cluster, name="Squad A")
        self.titles = seed_default_titles(self.tribe)
        self.user = User.objects.create_user(
            username="eu1", role=User.Role.END_USER, title=self.titles["data_scientist"], squad=self.squad
        )

    def _approved_day(self, day, part=HolidayRequestDay.DayPart.FULL):
        req = HolidayRequest.objects.create(requester=self.user)
        return HolidayRequestDay.objects.create(
            request=req, date=day, day_part=part, status=HolidayRequestDay.Status.APPROVED
        )

    def _find_weekday(self, month, weekday):
        """First date in self.year/month landing on the given weekday (0=Mon)."""
        d = date(self.year, month, 1)
        while d.weekday() != weekday:
            d += timedelta(days=1)
        return d

    def test_weekdays_in_quarter_matches_independent_calculation(self):
        for quarter in (1, 2, 3, 4):
            expected = _independent_weekday_count(self.year, quarter)
            actual = services._weekdays_in_quarter(self.year, quarter)
            self.assertEqual(actual, expected, f"quarter {quarter}")

    def test_full_day_absence_reduces_worked_and_increases_absence(self):
        monday = self._find_weekday(2, 0)  # a weekday in Q1
        self._approved_day(monday)
        members, metrics = services.compute_squad_metrics(self.squad, self.year)
        m = metrics[self.user.pk]
        self.assertEqual(m.absence_days[1], 1.0)
        self.assertEqual(m.worked_days[1], _independent_weekday_count(self.year, 1) - 1.0)

    def test_half_day_absence_counts_as_half_unit(self):
        monday = self._find_weekday(2, 0)
        self._approved_day(monday, part=HolidayRequestDay.DayPart.HALF)
        members, metrics = services.compute_squad_metrics(self.squad, self.year)
        m = metrics[self.user.pk]
        self.assertEqual(m.absence_days[1], 0.5)

    def test_bank_holiday_excluded_from_worked_and_not_counted_as_absence(self):
        weekday_bh = self._find_weekday(2, 2)  # a Wednesday in Q1
        BankHoliday.objects.create(tribe=self.tribe, date=weekday_bh, name="Test BH")
        members, metrics = services.compute_squad_metrics(self.squad, self.year)
        m = metrics[self.user.pk]
        self.assertEqual(m.worked_days[1], _independent_weekday_count(self.year, 1) - 1)
        self.assertEqual(m.absence_days[1], 0.0)

    def test_pending_and_refused_requests_excluded_from_metrics(self):
        monday = self._find_weekday(2, 0)
        pending = HolidayRequest.objects.create(requester=self.user)
        HolidayRequestDay.objects.create(request=pending, date=monday, day_part=HolidayRequestDay.DayPart.FULL)
        members, metrics = services.compute_squad_metrics(self.squad, self.year)
        m = metrics[self.user.pk]
        self.assertEqual(m.absence_days[1], 0.0)

    def test_over_cap_flag_is_based_on_worked_days_not_absence_days(self):
        total_weekdays = sum(_independent_weekday_count(self.year, q) for q in (1, 2, 3, 4))
        # Cap set 1 day below what this member would work with zero
        # absences, so with none taken they start out over the cap.
        with override_settings(ANNUAL_WORKED_DAYS_CAP=total_weekdays - 1):
            members, metrics = services.compute_squad_metrics(self.squad, self.year)
            m = metrics[self.user.pk]
            self.assertEqual(m.ytd_worked_total, total_weekdays)
            self.assertTrue(m.over_cap)

            # Taking one full day off brings worked days down to exactly the
            # cap - "over" is strict, so this is no longer over.
            monday = self._find_weekday(2, 0)
            self._approved_day(monday)
            members, metrics = services.compute_squad_metrics(self.squad, self.year)
            m = metrics[self.user.pk]
            self.assertEqual(m.ytd_worked_total, total_weekdays - 1)
            self.assertFalse(m.over_cap)

    @override_settings(ANNUAL_WORKED_DAYS_CAP=999999)
    def test_absence_days_alone_do_not_trigger_over_cap(self):
        # A member taking a lot of leave should not be flagged "over cap" -
        # only working too many days should be.
        for offset in range(10):
            monday = self._find_weekday(2, 0) + timedelta(weeks=offset)
            self._approved_day(monday)
        members, metrics = services.compute_squad_metrics(self.squad, self.year)
        m = metrics[self.user.pk]
        self.assertEqual(m.ytd_absence_total, 10.0)
        self.assertFalse(m.over_cap)

    def test_query_count_does_not_scale_with_member_count(self):
        for i in range(5):
            User.objects.create_user(
                username=f"extra{i}", role=User.Role.END_USER, title=self.titles["data_scientist"], squad=self.squad
            )
        members = list(self.squad.members.all())
        with self.assertNumQueries(2):
            services.compute_members_metrics(members, self.squad.tribe, self.year)
