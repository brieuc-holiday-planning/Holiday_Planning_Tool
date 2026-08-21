from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Tribe(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Cluster(models.Model):
    tribe = models.ForeignKey(Tribe, on_delete=models.CASCADE, related_name="clusters")
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["tribe__name", "name"]
        unique_together = [("tribe", "name")]

    def __str__(self):
        return f"{self.name} ({self.tribe})"


class Squad(models.Model):
    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE, related_name="squads")
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["cluster__tribe__name", "cluster__name", "name"]
        unique_together = [("cluster", "name")]

    def __str__(self):
        return f"{self.name} ({self.cluster})"

    @property
    def tribe(self):
        return self.cluster.tribe


class SquadWatcher(models.Model):
    squad = models.ForeignKey(Squad, on_delete=models.CASCADE, related_name="watchers")
    email = models.EmailField()

    class Meta:
        ordering = ["squad", "email"]
        unique_together = [("squad", "email")]

    def __str__(self):
        return f"{self.email} ({self.squad})"


class Title(models.Model):
    """A job function/profile (e.g. Data Scientist) within a Tribe. Scrum
    Masters manage the set of titles that exist - it's not fixed to any
    hardcoded list - and give each a short abbreviation used on the
    calendar's per-day working-count display.

    There's no separate "Scrum Master" role on User anymore - anyone whose
    title has grants_admin_access=True becomes an admin of the app (see
    accounts.User.is_scrum_master), independent of their `role` (Chapter
    Lead/End User), which is only about the holiday-approval workflow."""

    tribe = models.ForeignKey(Tribe, on_delete=models.CASCADE, related_name="titles")
    name = models.CharField(max_length=50)
    abbreviation = models.CharField(max_length=10)
    grants_admin_access = models.BooleanField(
        default=False,
        help_text="Anyone holding this title becomes an admin of the app (can reach /admin/ and manage the tribe).",
    )

    class Meta:
        ordering = ["tribe__name", "name"]
        unique_together = [("tribe", "name"), ("tribe", "abbreviation")]

    def __str__(self):
        return f"{self.name} ({self.abbreviation})"


class ChapterLeadAssignment(models.Model):
    """A backup approver for a Title: the *primary* Chapter Lead for a title
    is simply whichever User has role=Chapter Lead and that title (see
    accounts.User's one_chapter_lead_per_title constraint and
    holidays.services.resolve_chapter_lead) - set from the User admin, not
    here. This model is only for standing in for that primary when they're
    away: any user can be designated a backup for a title, and a title can
    have several backups."""

    tribe = models.ForeignKey(Tribe, on_delete=models.CASCADE, related_name="chapter_lead_assignments")
    title = models.ForeignKey(Title, on_delete=models.PROTECT, related_name="chapter_lead_assignments")
    chapter_lead = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="chapter_lead_for",
        verbose_name="backup approver",
    )

    class Meta:
        verbose_name = "backup chapter lead assignment"
        verbose_name_plural = "backup chapter lead assignments"
        ordering = ["tribe__name", "title__name"]
        unique_together = [("tribe", "title", "chapter_lead")]

    def __str__(self):
        return f"{self.chapter_lead} (backup for {self.title}, {self.tribe})"

    def clean(self):
        super().clean()
        if self.title_id and self.tribe_id and self.title.tribe_id != self.tribe_id:
            raise ValidationError({"title": "This title belongs to a different tribe."})
