from datetime import date

from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.urls import path

from apps.core.admin import ScrumMasterOnlyAdminMixin
from apps.org.models import Tribe

from .models import BankHoliday, Event, Sprint
from .services import generate_sprints_for_quarter


def _year_choices():
    """The only years anyone realistically plans sprints for: this one
    (the default), then next, then last. Evaluated per render rather than
    at import time so a long-running process rolls over at New Year."""
    current = date.today().year
    return [(year, str(year)) for year in (current, current + 1, current - 1)]


def _current_year():
    return date.today().year


class GenerateSprintsForm(forms.Form):
    tribe = forms.ModelChoiceField(queryset=Tribe.objects.all())
    year = forms.TypedChoiceField(choices=_year_choices, coerce=int, initial=_current_year)
    quarter = forms.ChoiceField(choices=Sprint.Quarter.choices)
    start_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}), help_text="Must be a Monday."
    )
    end_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}), help_text="Must be a Friday."
    )


@admin.register(Sprint)
class SprintAdmin(ScrumMasterOnlyAdminMixin, admin.ModelAdmin):
    """Sprints are only ever created a whole quarter at a time, through
    "Generate sprints for a quarter" (see generate_view below), which keeps
    them contiguous, correctly numbered SP1..SPn and Monday-to-Friday.
    Adding one by hand would sidestep all of that, so it's disabled -
    existing sprints can still be edited or deleted to fix a mistake."""

    list_display = ("name", "tribe", "year", "quarter", "start_date", "end_date")
    list_filter = ("tribe", "year", "quarter")
    change_list_template = "admin/calendar_data/sprint/change_list.html"

    def has_add_permission(self, request):
        return False

    def get_urls(self):
        custom = [
            path(
                "generate/",
                self.admin_site.admin_view(self.generate_view),
                name="calendar_data_sprint_generate",
            ),
        ]
        return custom + super().get_urls()

    def generate_view(self, request):
        if not self._is_scrum_master(request):
            raise PermissionDenied

        if request.method == "POST":
            form = GenerateSprintsForm(request.POST)
            if form.is_valid():
                try:
                    sprints = generate_sprints_for_quarter(
                        tribe=form.cleaned_data["tribe"],
                        year=form.cleaned_data["year"],
                        quarter=int(form.cleaned_data["quarter"]),
                        start_date=form.cleaned_data["start_date"],
                        end_date=form.cleaned_data["end_date"],
                    )
                except ValidationError as exc:
                    for message in exc.messages:
                        form.add_error(None, message)
                else:
                    self.message_user(request, f"Generated {len(sprints)} sprint(s): "
                                       f"{', '.join(s.name for s in sprints)}.")
                    return redirect("admin:calendar_data_sprint_changelist")
        else:
            form = GenerateSprintsForm()

        context = {
            **self.admin_site.each_context(request),
            "form": form,
            "title": "Generate sprints for a quarter",
            "opts": self.model._meta,
        }
        return render(request, "admin/calendar_data/sprint/generate_form.html", context)


@admin.register(BankHoliday)
class BankHolidayAdmin(ScrumMasterOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("name", "tribe", "date")
    list_filter = ("tribe",)


@admin.register(Event)
class EventAdmin(ScrumMasterOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("name", "scope", "tribe", "cluster", "squad", "start_date", "end_date")
    list_filter = ("tribe", "scope")
