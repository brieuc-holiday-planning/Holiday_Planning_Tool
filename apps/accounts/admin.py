from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import Permission

from apps.core.admin import ScrumMasterOnlyAdminMixin
from apps.holidays.services import SILENT_EDIT_PERM, resync_pending_routing_for_title

from .models import User
from .services import sync_is_staff

SILENT_EDIT_FIELD = "can_edit_holidays_silently"
SILENT_EDIT_LABEL = "Can silently edit any holiday request"
SILENT_EDIT_HELP = (
    "Grants a permission (holidays.edit_any_holiday_silently) that lets this user directly add, "
    "edit, or delete any user's holiday requests in the admin - bypassing the normal submit/"
    "approve/refuse workflow, so the chapter lead is never emailed about these changes."
)


class _SilentEditPermFieldMixin(forms.ModelForm):
    can_edit_holidays_silently = forms.BooleanField(
        required=False, label=SILENT_EDIT_LABEL, help_text=SILENT_EDIT_HELP
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields[SILENT_EDIT_FIELD].initial = self.instance.has_perm(SILENT_EDIT_PERM)


class HolidayUserChangeForm(_SilentEditPermFieldMixin, UserChangeForm):
    pass


class HolidayUserCreationForm(_SilentEditPermFieldMixin, UserCreationForm):
    pass


@admin.register(User)
class UserAdmin(ScrumMasterOnlyAdminMixin, DjangoUserAdmin):
    form = HolidayUserChangeForm
    add_form = HolidayUserCreationForm

    list_display = ("username", "get_full_name", "role", "title", "squad", "is_active")
    list_filter = ("role", "title", "squad", "is_active")
    search_fields = ("username", "first_name", "last_name", "email")
    ordering = ("username",)

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email")}),
        ("Holiday tool", {"fields": ("role", "title", "squad")}),
        ("Special permissions", {"fields": (SILENT_EDIT_FIELD,)}),
        ("Status", {"fields": ("is_active",)}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "password1",
                    "password2",
                    "first_name",
                    "last_name",
                    "email",
                    "role",
                    "title",
                    "squad",
                    SILENT_EDIT_FIELD,
                ),
            },
        ),
    )
    readonly_fields = ("last_login", "date_joined")

    def get_full_name(self, obj):
        return obj.get_full_name()

    get_full_name.short_description = "Name"

    def get_fieldsets(self, request, obj=None):
        # is_staff is derived automatically from role (see User.save()) and
        # shown read-only for information. is_superuser/groups/
        # user_permissions are only ever exposed to the break-glass
        # superuser - a Scrum Master must never be able to self-escalate to
        # superuser or grant raw Django permissions through this form (the
        # one specific permission above is the sole narrow exception).
        fieldsets = super().get_fieldsets(request, obj)
        if request.user.is_superuser:
            fieldsets = fieldsets + (
                ("Django admin access (superuser only)", {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")}),
            )
        return fieldsets

    def get_readonly_fields(self, request, obj=None):
        return super().get_readonly_fields(request, obj) + ("is_staff",)

    def save_model(self, request, obj, form, change):
        # Capture who this title's primary Chapter Lead was *before* this
        # save, so we know afterward which title(s) need their in-flight
        # requests re-routed (the title they're leaving, if any, and the
        # title they now cover as of this save).
        old_role, old_title_id = None, None
        if change:
            old = User.objects.get(pk=obj.pk)
            old_role, old_title_id = old.role, old.title_id

        super().save_model(request, obj, form, change)

        grant = form.cleaned_data.get(SILENT_EDIT_FIELD, False)
        perm = Permission.objects.get(
            content_type__app_label="holidays", codename="edit_any_holiday_silently"
        )
        if grant:
            obj.user_permissions.add(perm)
        else:
            obj.user_permissions.remove(perm)

        # User.save() (called above via super().save_model()) computed
        # is_staff before this permission change was persisted to the M2M,
        # so it couldn't have accounted for it - top up now that it has.
        # Someone who only holds this permission (not an admin title or
        # superuser) still needs is_staff to reach /admin/ at all.
        sync_is_staff(obj, silent_edit=grant)

        # Assigning role=Chapter Lead + a title here *is* how someone
        # becomes the validator for that title's holiday requests (see
        # holidays.services.resolve_chapter_lead) - resync in-flight
        # requests for whichever title(s) this save affected coverage of.
        affected_title_ids = set()
        if old_role == User.Role.CHAPTER_LEAD and old_title_id:
            affected_title_ids.add(old_title_id)
        if obj.role == User.Role.CHAPTER_LEAD and obj.title_id:
            affected_title_ids.add(obj.title_id)
        for title_id in affected_title_ids:
            resync_pending_routing_for_title(title_id)
