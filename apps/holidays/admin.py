from django.contrib import admin

from apps.core.admin import ScrumMasterOnlyAdminMixin

from .models import HolidayRequest, HolidayRequestDay
from .services import SILENT_EDIT_PERM


class HolidayRequestDayInline(ScrumMasterOnlyAdminMixin, admin.TabularInline):
    model = HolidayRequestDay
    extra = 0
    fields = ("date", "day_part", "status", "decided_by", "decided_at", "decision_reason")

    def has_view_permission(self, request, obj=None):
        return self._is_scrum_master(request) or request.user.has_perm(SILENT_EDIT_PERM)

    def has_add_permission(self, request, obj=None):
        return request.user.has_perm(SILENT_EDIT_PERM)

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm(SILENT_EDIT_PERM)

    def has_delete_permission(self, request, obj=None):
        return request.user.has_perm(SILENT_EDIT_PERM)


@admin.register(HolidayRequest)
class HolidayRequestAdmin(ScrumMasterOnlyAdminMixin, admin.ModelAdmin):
    """Read-only for Scrum Masters (audit only - status changes normally go
    through the workflow views in holidays/views.py so approval/refusal
    emails fire). A user holding SILENT_EDIT_PERM gets full add/change/
    delete instead, for direct DB corrections that must NOT notify anyone."""

    list_display = ("requester", "routed_chapter_lead", "submitted_at")
    list_filter = ("requester__squad",)
    inlines = [HolidayRequestDayInline]

    def has_view_permission(self, request, obj=None):
        return self._is_scrum_master(request) or request.user.has_perm(SILENT_EDIT_PERM)

    def has_add_permission(self, request):
        return request.user.has_perm(SILENT_EDIT_PERM)

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm(SILENT_EDIT_PERM)

    def has_delete_permission(self, request, obj=None):
        return request.user.has_perm(SILENT_EDIT_PERM)

    def has_module_permission(self, request):
        return self._is_scrum_master(request) or request.user.has_perm(SILENT_EDIT_PERM)
