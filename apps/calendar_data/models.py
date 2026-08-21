from django.core.exceptions import ValidationError
from django.db import models

from apps.org.models import Cluster, Squad, Tribe


class Sprint(models.Model):
    class Quarter(models.IntegerChoices):
        Q1 = 1, "Q1"
        Q2 = 2, "Q2"
        Q3 = 3, "Q3"
        Q4 = 4, "Q4"

    tribe = models.ForeignKey(Tribe, on_delete=models.CASCADE, related_name="sprints")
    # Sprints are generated in one batch per (tribe, year, quarter) - see
    # calendar_data.services.generate_sprints_for_quarter - and numbering
    # (SP1, SP2, ...) restarts with each new batch, so uniqueness of `name`
    # is scoped to the batch rather than global to the tribe.
    year = models.PositiveIntegerField()
    quarter = models.PositiveSmallIntegerField(choices=Quarter.choices)
    name = models.CharField(max_length=20, help_text="e.g. SP1, SP2, SP3")
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        ordering = ["tribe__name", "year", "quarter", "start_date"]
        unique_together = [("tribe", "year", "quarter", "name")]
        constraints = [
            models.CheckConstraint(
                check=models.Q(end_date__gte=models.F("start_date")),
                name="sprint_end_after_start",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.get_quarter_display()} {self.year}: {self.start_date} - {self.end_date})"

    @property
    def display_label(self) -> str:
        """e.g. "Q3SP4" - how the sprint is labelled on the calendar, so
        it's clear which quarter it belongs to at a glance."""
        return f"Q{self.quarter}{self.name}"

    @classmethod
    def overlapping(cls, tribe, start_date, end_date, exclude_pk=None):
        """Sprints in `tribe` whose dates intersect [start_date, end_date].
        Two ranges overlap exactly when each one starts on or before the
        other ends. A week may only ever be covered by one sprint, so this
        backs the no-overlap rule in both places sprints can be written:
        generation (services.generate_sprints_for_quarter) and editing an
        existing one in the admin (see clean below)."""
        sprints = cls.objects.filter(tribe=tribe, start_date__lte=end_date, end_date__gte=start_date)
        if exclude_pk is not None:
            sprints = sprints.exclude(pk=exclude_pk)
        return sprints

    def clean(self):
        super().clean()
        if not (self.tribe_id and self.start_date and self.end_date):
            return
        if self.end_date < self.start_date:
            return  # reported by the sprint_end_after_start constraint
        clash = self.overlapping(
            self.tribe_id, self.start_date, self.end_date, exclude_pk=self.pk
        ).first()
        if clash:
            raise ValidationError(
                {
                    "start_date": (
                        f"These dates overlap an existing sprint: {clash}. "
                        "A week can only be covered by one sprint - delete that one first."
                    )
                }
            )


class BankHoliday(models.Model):
    tribe = models.ForeignKey(Tribe, on_delete=models.CASCADE, related_name="bank_holidays")
    date = models.DateField()
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["tribe__name", "date"]
        unique_together = [("tribe", "date")]

    def __str__(self):
        return f"{self.name} ({self.date})"


class Event(models.Model):
    class Scope(models.TextChoices):
        TRIBE = "tribe", "Tribe"
        CLUSTER = "cluster", "Cluster"
        SQUAD = "squad", "Squad"

    tribe = models.ForeignKey(Tribe, on_delete=models.CASCADE, related_name="events")
    scope = models.CharField(max_length=10, choices=Scope.choices)
    cluster = models.ForeignKey(
        Cluster, null=True, blank=True, on_delete=models.CASCADE, related_name="events"
    )
    squad = models.ForeignKey(
        Squad, null=True, blank=True, on_delete=models.CASCADE, related_name="events"
    )
    name = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField()
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["tribe__name", "start_date"]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(scope="tribe", cluster__isnull=True, squad__isnull=True)
                    | models.Q(scope="cluster", cluster__isnull=False, squad__isnull=True)
                    | models.Q(scope="squad", squad__isnull=False)
                ),
                name="event_scope_matches_fk",
            ),
            models.CheckConstraint(
                check=models.Q(end_date__gte=models.F("start_date")),
                name="event_end_after_start",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.start_date} - {self.end_date})"

    def clean(self):
        super().clean()
        errors = {}
        if self.scope == self.Scope.TRIBE and (self.cluster_id or self.squad_id):
            errors["scope"] = "Tribe-scoped events must not set cluster or squad."
        elif self.scope == self.Scope.CLUSTER and (not self.cluster_id or self.squad_id):
            errors["cluster"] = "Cluster-scoped events must set cluster and not squad."
        elif self.scope == self.Scope.SQUAD and not self.squad_id:
            errors["squad"] = "Squad-scoped events must set squad."
        if errors:
            raise ValidationError(errors)
