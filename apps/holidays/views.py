import json
from datetime import date, datetime
from functools import wraps

from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.accounts.services import member_counts_by_title
from apps.org.models import Squad
from apps.org.services import clusters_with_squads

from . import services
from .models import HolidayRequest, HolidayRequestDay
from .services import SILENT_EDIT_PERM


def approver_required(view_func):
    """Restricts a view to users who can act as a Chapter Lead for at least
    one title - the primary (role=Chapter Lead) or a designated backup.
    Unlike role_required, this isn't tied to the `role` field alone, since
    any user can be designated a backup approver."""

    @wraps(view_func)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not services.is_approver(request.user):
            raise PermissionDenied("You are not authorized to approve holiday requests.")
        return view_func(request, *args, **kwargs)

    return wrapped


@login_required
def squad_calendar(request, squad_id):
    # Any authenticated user can view any squad's calendar across the whole
    # tribe (holidays are visible tribe-wide); only submit_request below
    # restricts *submitting* a request to the user's own squad.
    squad = get_object_or_404(Squad, pk=squad_id)
    is_own_squad = request.user.squad_id == squad.pk
    # Silently setting a squad member's day status (bypassing the normal
    # approve/refuse workflow) is restricted to SILENT_EDIT_PERM holders
    # editing their OWN squad - same is_own_squad check as the request
    # builder below.
    can_silent_edit = is_own_squad and request.user.has_perm(SILENT_EDIT_PERM)
    title_totals = member_counts_by_title(squad.members.all(), squad.tribe)
    context = {
        "squad": squad,
        "is_own_squad": is_own_squad,
        "can_silent_edit": can_silent_edit,
        "day_part_choices": HolidayRequestDay.DayPart.choices,
        "title_totals": title_totals,
        # Pre-filtered to titles actually present in the squad, so the
        # legend can join them with separators without an orphaned
        # trailing/leading one when a zero-count title sits at either end.
        "active_title_totals": [t for t in title_totals if t["total"]],
        "my_requests": (
            HolidayRequest.objects.filter(requester=request.user).prefetch_related("days")[:10]
            if is_own_squad
            else []
        ),
        "clusters_with_squads": clusters_with_squads(squad.tribe, "holidays:squad_calendar"),
    }
    if can_silent_edit:
        # A Chapter Lead's own holiday status can never be edited this way,
        # even if they happen to belong to this squad - so they're not
        # offered as a target at all.
        context["squad_members"] = squad.members.exclude(role=User.Role.CHAPTER_LEAD).order_by("username")
    return render(request, "holidays/squad_calendar.html", context)


@login_required
def calendar_feed(request, squad_id):
    squad = get_object_or_404(Squad, pk=squad_id)
    start = _parse_date(request.GET.get("start")) or date.today().replace(month=1, day=1)
    end = _parse_date(request.GET.get("end")) or date.today().replace(month=12, day=31)
    events = services.calendar_feed_events(squad, start, end)
    return JsonResponse(events, safe=False)


def _parse_date(value):
    if not value:
        return None
    # FullCalendar sends full ISO datetimes for the visible range.
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


@login_required
@require_POST
def submit_request(request, squad_id):
    squad = get_object_or_404(Squad, pk=squad_id)
    if request.user.squad_id != squad.pk:
        raise PermissionDenied("You can only submit requests for your own squad.")

    try:
        raw_days = json.loads(request.POST.get("days_json", "[]"))
        day_entries = [
            (datetime.strptime(entry["date"], "%Y-%m-%d").date(), entry["day_part"])
            for entry in raw_days
        ]
        services.submit_request(request.user, day_entries, note=request.POST.get("note", ""))
    except (ValidationError, ValueError, KeyError) as exc:
        message = exc.message if isinstance(exc, ValidationError) else str(exc)
        messages.error(request, f"Could not submit request: {message}")
    else:
        messages.success(request, "Holiday request submitted.")

    return redirect("holidays:squad_calendar", squad_id=squad.pk)


@login_required
@require_POST
def silent_edit_status(request, squad_id):
    squad = get_object_or_404(Squad, pk=squad_id)
    if not request.user.has_perm(SILENT_EDIT_PERM) or request.user.squad_id != squad.pk:
        raise PermissionDenied("You are not authorized to edit this squad's holiday status.")

    member = get_object_or_404(User, pk=request.POST.get("member_id"), squad=squad)
    try:
        raw_days = json.loads(request.POST.get("days_json", "[]"))
        day_entries = [
            (
                datetime.strptime(entry["date"], "%Y-%m-%d").date(),
                entry["action"],
                entry.get("day_part", "full"),
            )
            for entry in raw_days
        ]
        services.silently_set_day_status(
            request.user, member, day_entries, comment=request.POST.get("comment", "")
        )
    except (ValidationError, ValueError, KeyError) as exc:
        message = exc.message if isinstance(exc, ValidationError) else str(exc)
        messages.error(request, f"Could not update status: {message}")
    else:
        messages.success(request, f"Updated {member}'s holiday status.")

    return redirect("holidays:squad_calendar", squad_id=squad.pk)


# The decided list is a full history, so it is paged rather than truncated.
DECIDED_PER_PAGE = 25

# Carried through pagination links and across approve/refuse, so acting on
# one day never resets the view the approver had set up.
INBOX_VIEW_PARAMS = ("pending_requester", "decided_requester", "page")


def _inbox_url(values):
    """The inbox URL with whichever of INBOX_VIEW_PARAMS are set."""
    query = urlencode({key: value for key, value in values.items() if value})
    url = reverse("holidays:approval_inbox")
    return f"{url}?{query}" if query else url


def _requester_options(day_qs, selected_id):
    """Requesters to offer in a filter dropdown: everyone appearing in the
    unfiltered list, plus whoever is currently selected.

    Keeping the selection in the list matters after a decision - approving
    someone's last pending day would otherwise drop them from the options,
    so the dropdown would snap back to "Everyone" and the filter would look
    like it had been lost even though it is still applied.
    """
    ids = set(day_qs.values_list("request__requester_id", flat=True))
    if selected_id:
        try:
            ids.add(int(selected_id))
        except (TypeError, ValueError):
            pass
    return User.objects.filter(pk__in=ids).order_by("username")


@approver_required
def approval_inbox(request):
    """Every day (full or half) submitted for a title this user can approve
    (as primary Chapter Lead or as a designated backup) is its own line to
    approve or refuse - a multi-day request can end up partly approved and
    partly refused. Pending and decided days can each be filtered down to
    one requester; the decided list is the complete history, paged."""
    approvable_title_ids = services.approvable_title_ids_for(request.user)

    pending_qs = (
        services.pending_days_for(request.user)
        .select_related("request", "request__requester", "request__requester__squad")
        .order_by("date")
    )
    pending_requester_id = request.GET.get("pending_requester") or ""
    pending_requesters = _requester_options(pending_qs, pending_requester_id)
    if pending_requester_id:
        pending_qs = pending_qs.filter(request__requester_id=pending_requester_id)

    decided_qs = (
        HolidayRequestDay.objects.filter(request__requester__title_id__in=approvable_title_ids)
        .exclude(status=HolidayRequestDay.Status.PENDING)
        .select_related("request", "request__requester", "decided_by")
        .order_by("-decided_at", "-pk")
    )
    decided_requester_id = request.GET.get("decided_requester") or ""
    decided_requesters = _requester_options(decided_qs, decided_requester_id)
    if decided_requester_id:
        decided_qs = decided_qs.filter(request__requester_id=decided_requester_id)

    decided_page = Paginator(decided_qs, DECIDED_PER_PAGE).get_page(request.GET.get("page"))

    # Everything except `page`, for pagination links to append their own.
    filter_query = urlencode(
        {
            key: value
            for key, value in (
                ("pending_requester", pending_requester_id),
                ("decided_requester", decided_requester_id),
            )
            if value
        }
    )

    return render(
        request,
        "holidays/approval_inbox.html",
        {
            "pending": pending_qs,
            "pending_requesters": pending_requesters,
            "selected_pending_requester": pending_requester_id,
            "decided": decided_page,
            "decided_page": decided_page,
            "decided_total": decided_page.paginator.count,
            "decided_requesters": decided_requesters,
            "selected_decided_requester": decided_requester_id,
            "filter_query": filter_query,
        },
    )


def _decide_and_return(request, day_id, decide):
    """Shared approve/refuse plumbing: act on the day, then return the
    approver to exactly the filtered page they came from."""
    day = get_object_or_404(HolidayRequestDay, pk=day_id)
    try:
        decide(day)
    except ValidationError as exc:
        messages.error(request, exc.message)
    return redirect(_inbox_url({key: request.POST.get(key, "") for key in INBOX_VIEW_PARAMS}))


@approver_required
@require_POST
def approve_day(request, day_id):
    def decide(day):
        services.approve_day(day, request.user)
        messages.success(request, f"Approved {day.request.requester}'s {day.date} request.")

    return _decide_and_return(request, day_id, decide)


@approver_required
@require_POST
def refuse_day(request, day_id):
    def decide(day):
        services.refuse_day(day, request.user, reason=request.POST.get("reason", ""))
        messages.success(request, f"Refused {day.request.requester}'s {day.date} request.")

    return _decide_and_return(request, day_id, decide)
