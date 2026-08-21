from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        CHAPTER_LEAD = "chapter_lead", "Chapter Lead"
        END_USER = "end_user", "End User"

    # `role` is only about the holiday-approval workflow (who approves
    # whose requests) - it is NOT how someone becomes an admin of the app.
    # There is deliberately no "Scrum Master" role: admin access is granted
    # purely by title (see is_scrum_master below), so it can be handed to
    # anyone - a Chapter Lead or an End User - just by giving them that
    # title, without changing how their own holiday requests are routed.
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.END_USER)
    # A Title (job function/profile) is admin-managed per Tribe - see
    # org.Title - not a fixed set. PROTECT so a title in use can't be
    # deleted out from under a user.
    title = models.ForeignKey("org.Title", on_delete=models.PROTECT, related_name="users")
    squad = models.ForeignKey(
        "org.Squad",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="members",
    )

    class Meta:
        constraints = [
            # A Chapter Lead's title is what makes them the validator for
            # that title's holiday requests (see holidays.services.
            # resolve_chapter_lead), so there can only be one per title.
            models.UniqueConstraint(
                fields=["title"],
                condition=models.Q(role="chapter_lead"),
                name="one_chapter_lead_per_title",
            ),
        ]

    @property
    def is_scrum_master(self):
        """True if this user is an admin of the app - purely a function of
        their title (see org.Title.grants_admin_access), independent of
        `role`. There's no dedicated "Scrum Master" role: whoever holds an
        admin-granting title becomes an admin, whatever their approval
        role is."""
        return bool(self.title_id and self.title.grants_admin_access)

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError

        # A squad is required for anyone except a Chapter Lead (who
        # approves requests tribe-wide by title, not by squad) or an admin
        # (who manages the tribe rather than belonging to one squad's
        # day-to-day work) - both may optionally still belong to a squad.
        squad_optional = self.role == self.Role.CHAPTER_LEAD or self.is_scrum_master
        if not squad_optional and self.squad_id is None:
            raise ValidationError({"squad": "A squad is required for this role."})

    def save(self, *args, **kwargs):
        # Auto-*elevate* only: an app admin (see is_scrum_master) or
        # superuser always gets is_staff, from any code path, so they can
        # always reach /admin/. We deliberately never auto-*demote* it
        # here, because is_staff can also be earned independently by
        # holding the holidays.edit_any_holiday_silently permission (see
        # accounts/admin.py) - checking that would need this row and its
        # user_permissions to already be in the DB, which isn't true yet on
        # a first save. UserAdmin.save_model (and org.admin.TitleAdmin, for
        # title-driven changes) recompute and correct is_staff in both
        # directions once everything is settled; a User saved outside the
        # admin (shell, another management command) that needs is_staff
        # turned off after losing admin access must do so explicitly.
        if self.is_superuser or self.is_scrum_master:
            self.is_staff = True
        super().save(*args, **kwargs)

    def __str__(self):
        return self.get_full_name() or self.username
