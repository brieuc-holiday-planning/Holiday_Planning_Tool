import calendar
from dataclasses import dataclass, field
from datetime import date

from django.conf import settings

from apps.calendar_data.models import BankHoliday
from apps.holidays.models import HolidayRequestDay

QUARTERS = (1, 2, 3, 4)


@dataclass
class QuarterMetrics:
    worked_days: dict = field(default_factory=dict)
    absence_days: dict = field(default_factory=dict)
    ytd_absence_total: float = 0.0
    ytd_worked_total: float = 0.0
    annual_cap: int = 220

    @property
    def over_cap(self) -> bool:
        # The cap applies to worked days (e.g. a French "forfait jours"
        # contractual max), not absence days - exceeding it means this
        # member is on track to work more than their contractual maximum
        # and should be taking more time off.
        return self.ytd_worked_total > self.annual_cap

    @property
    def cap_pct(self) -> int:
        """Worked days as a whole percentage of the annual cap, clamped to
        100 so it can drive a fixed-width progress bar. Lives here next to
        over_cap so every reading of "worked vs cap" comes from one place;
        over_cap remains the source of truth for whether it's exceeded."""
        if not self.annual_cap:
            return 0
        return min(round(self.ytd_worked_total / self.annual_cap * 100), 100)


def _quarter_of(d: date) -> int:
    return (d.month - 1) // 3 + 1


def _weekdays_in_quarter(year: int, quarter: int) -> int:
    start_month = (quarter - 1) * 3 + 1
    count = 0
    for month in range(start_month, start_month + 3):
        _, days_in_month = calendar.monthrange(year, month)
        for day_num in range(1, days_in_month + 1):
            if date(year, month, day_num).weekday() < 5:
                count += 1
    return count


def compute_members_metrics(members, tribe, year) -> dict:
    """Returns {user_id: QuarterMetrics} for the given members, in at most
    two queries regardless of how many members there are."""
    annual_cap = settings.ANNUAL_WORKED_DAYS_CAP
    member_ids = [m.pk for m in members]

    bank_holidays_per_quarter = {q: 0 for q in QUARTERS}
    if tribe:
        for d in BankHoliday.objects.filter(tribe=tribe, date__year=year).values_list("date", flat=True):
            if d.weekday() < 5:
                bank_holidays_per_quarter[_quarter_of(d)] += 1

    absence_by_user_quarter = {uid: {q: 0.0 for q in QUARTERS} for uid in member_ids}
    day_rows = HolidayRequestDay.objects.filter(
        request__requester_id__in=member_ids,
        status=HolidayRequestDay.Status.APPROVED,
        date__year=year,
    ).values_list("request__requester_id", "date", "day_part")
    for uid, d, part in day_rows:
        units = 1.0 if part == HolidayRequestDay.DayPart.FULL else 0.5
        absence_by_user_quarter[uid][_quarter_of(d)] += units

    weekdays_per_quarter = {q: _weekdays_in_quarter(year, q) for q in QUARTERS}

    results = {}
    for uid in member_ids:
        absences = absence_by_user_quarter[uid]
        worked = {
            q: weekdays_per_quarter[q] - bank_holidays_per_quarter[q] - absences[q] for q in QUARTERS
        }
        results[uid] = QuarterMetrics(
            worked_days=worked,
            absence_days=absences,
            ytd_absence_total=sum(absences.values()),
            ytd_worked_total=sum(worked.values()),
            annual_cap=annual_cap,
        )
    return results


def compute_squad_metrics(squad, year):
    members = list(squad.members.select_related("squad").all())
    return members, compute_members_metrics(members, squad.tribe, year)


def compute_cluster_metrics(cluster, year):
    from apps.accounts.models import User

    members = list(User.objects.filter(squad__cluster=cluster).select_related("squad"))
    return members, compute_members_metrics(members, cluster.tribe, year)
