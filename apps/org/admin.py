from django.contrib import admin

from apps.core.admin import ScrumMasterOnlyAdminMixin

from .models import ChapterLeadAssignment, Cluster, Squad, SquadWatcher, Tribe, Title


class SquadWatcherInline(admin.TabularInline):
    model = SquadWatcher
    extra = 1


class ClusterInline(admin.TabularInline):
    model = Cluster
    extra = 0
    show_change_link = True


class SquadInline(admin.TabularInline):
    model = Squad
    extra = 0
    show_change_link = True


@admin.register(Tribe)
class TribeAdmin(ScrumMasterOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("name",)
    inlines = [ClusterInline]


@admin.register(Cluster)
class ClusterAdmin(ScrumMasterOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("name", "tribe")
    list_filter = ("tribe",)
    inlines = [SquadInline]


@admin.register(Squad)
class SquadAdmin(ScrumMasterOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("name", "cluster", "tribe")
    list_filter = ("cluster__tribe", "cluster")
    inlines = [SquadWatcherInline]

    def tribe(self, obj):
        return obj.tribe


@admin.register(SquadWatcher)
class SquadWatcherAdmin(ScrumMasterOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("email", "squad")
    list_filter = ("squad",)


@admin.register(Title)
class TitleAdmin(ScrumMasterOnlyAdminMixin, admin.ModelAdmin):
    """The set of titles (job functions) is entirely admin-managed per
    tribe - not limited to any fixed list - each with a short abbreviation
    used on the calendar's per-day working-count display.

    grants_admin_access is what makes someone an admin of the app (see
    accounts.User.is_scrum_master) - there's no separate role for it, so
    toggling it here must resync is_staff for everyone who holds this
    title (a User admin save resyncs its own row automatically, but
    editing the title itself doesn't touch those User rows)."""

    list_display = ("name", "abbreviation", "tribe", "grants_admin_access")
    list_filter = ("tribe", "grants_admin_access")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        from apps.accounts.services import sync_is_staff

        for user in obj.users.all():
            sync_is_staff(user)


@admin.register(ChapterLeadAssignment)
class ChapterLeadAssignmentAdmin(ScrumMasterOnlyAdminMixin, admin.ModelAdmin):
    """Backup approvers only - the primary Chapter Lead for a title is set
    on the User admin (assign them role=Chapter Lead + that title), not
    here. Any user can be designated a backup, and a title can have several,
    so they can stand in for the primary when they're away."""

    list_display = ("title", "chapter_lead", "tribe")
    list_filter = ("tribe", "title")
