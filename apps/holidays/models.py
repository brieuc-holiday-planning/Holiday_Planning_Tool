from django.conf import settings
from django.db import models


class HolidayRequest(models.Model):
    """A submission covering one or more days (see HolidayRequestDay).
    Approval happens per-day, not for the request as a whole - a chapter
    lead may accept some days and refuse others from the same submission."""

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="holiday_requests"
    )
    # Resolved once at submission time (see services.resolve_chapter_lead) and
    # snapshotted, so a later change to the tribe's title->lead mapping never
    # rewrites who was actually responsible for a past decision.
    routed_chapter_lead = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="routed_requests",
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-submitted_at"]
        permissions = [
            (
                "edit_any_holiday_silently",
                "Can directly edit any user's holiday requests without notifying the chapter lead",
            ),
        ]

    def __str__(self):
        return f"{self.requester} ({self.submitted_at:%Y-%m-%d})"

    @property
    def total_units(self) -> float:
        return sum(day.units for day in self.days.all())


class HolidayRequestDay(models.Model):
    class DayPart(models.TextChoices):
        FULL = "full", "Full day"
        HALF = "half", "Half day"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REFUSED = "refused", "Refused"
        # Only reachable via the silent-edit permission's "cancel" action
        # (see holidays.services.silently_set_day_status) - distinct from
        # REFUSED, which means a Chapter Lead declined a request. A
        # cancelled day is excluded from the calendar feed and metrics,
        # same as if it never existed, but the row (and its comment) is
        # kept for the audit trail in the approval inbox.
        CANCELLED = "cancelled", "Cancelled"

    request = models.ForeignKey(HolidayRequest, on_delete=models.CASCADE, related_name="days")
    date = models.DateField()
    day_part = models.CharField(max_length=4, choices=DayPart.choices, default=DayPart.FULL)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="holiday_day_decisions",
    )
    decision_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["date"]
        unique_together = [("request", "date")]

    def __str__(self):
        return f"{self.date} ({self.get_day_part_display()}) - {self.get_status_display()}"

    @property
    def units(self) -> float:
        return 1.0 if self.day_part == self.DayPart.FULL else 0.5
