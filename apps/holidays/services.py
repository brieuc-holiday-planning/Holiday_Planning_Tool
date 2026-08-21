from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.calendar_data.models import BankHoliday
from apps.core.emails import (
    notify_approved_day_cancelled,
    notify_day_approved,
    notify_day_refused,
    notify_request_submitted,
    notify_silent_edit,
)

from .models import HolidayRequest, HolidayRequestDay

# Grantable per-user via the User admin (see accounts/admin.py). A holder of
# this permission gets full add/change/delete on holiday requests in the
# admin (see holidays/admin.py), plus the ability to directly set a squad
# member's day status from that squad's calendar (see
# silently_set_day_status below) - both bypass the normal submit/approve/
# refuse workflow.
SILENT_EDIT_PERM = "holidays.edit_any_holiday_silently"


def resolve_chapter_lead(user):
    """The primary Chapter Lead for `user`'s holiday requests is simply
    whichever User has role=Chapter Lead and shares `user.title` - the
    accounts.User.one_chapter_lead_per_title constraint guarantees there's
    at most one, and it's set just by assigning that role+title on the User
    admin (see accounts.admin.UserAdmin.save_model). Routing is by title,
    not by squad.

    Falls back to any active admin (see accounts.User.is_scrum_master) if
    there's no primary for this title, or if the resolved lead would be the
    requester themselves (a Chapter Lead whose own title routes back to
    them).
    """
    from apps.accounts.models import User

    lead = User.objects.filter(role=User.Role.CHAPTER_LEAD, title_id=user.title_id).first()

    if lead is None or lead.pk == user.pk:
        lead = (
            User.objects.filter(title__grants_admin_access=True, is_active=True)
            .exclude(pk=user.pk)
            .order_by("pk")
            .first()
        )
    return lead


def resync_pending_routing_for_title(title):
    """Re-resolves routed_chapter_lead for every request with at least one
    still-pending day, submitted by a user with this title. Called whenever
    the title's primary Chapter Lead changes (assigned, reassigned, or
    removed via the User admin) so in-flight requests follow the new
    assignment rather than staying pinned to whoever it used to be -
    already-decided days are untouched, since their decision is history."""
    requests = (
        HolidayRequest.objects.filter(
            requester__title=title, days__status=HolidayRequestDay.Status.PENDING
        )
        .distinct()
        .select_related("requester")
    )
    for req in requests:
        new_lead = resolve_chapter_lead(req.requester)
        new_lead_id = new_lead.pk if new_lead else None
        if req.routed_chapter_lead_id != new_lead_id:
            req.routed_chapter_lead_id = new_lead_id
            req.save(update_fields=["routed_chapter_lead"])


def is_approver(user):
    """True if `user` can act as a Chapter Lead for at least one title -
    either as the primary (role=Chapter Lead) or as a designated backup
    (see org.ChapterLeadAssignment)."""
    from apps.org.models import ChapterLeadAssignment

    if user.role == user.Role.CHAPTER_LEAD:
        return True
    return ChapterLeadAssignment.objects.filter(chapter_lead=user).exists()


def approvable_title_ids_for(user):
    """Title ids whose holiday requests `user` may see/decide - their own
    title if they're its primary Chapter Lead, plus any title they're a
    designated backup for."""
    from apps.org.models import ChapterLeadAssignment

    title_ids = set(
        ChapterLeadAssignment.objects.filter(chapter_lead=user).values_list("title_id", flat=True)
    )
    if user.role == user.Role.CHAPTER_LEAD and user.title_id:
        title_ids.add(user.title_id)
    return title_ids


def pending_days_for(user):
    """Every still-pending day `user` is responsible for deciding, across
    every title they cover as primary or backup. One definition shared by
    the approval inbox and the nav badge so the two can never disagree."""
    title_ids = approvable_title_ids_for(user)
    if not title_ids:
        return HolidayRequestDay.objects.none()
    return HolidayRequestDay.objects.filter(
        request__requester__title_id__in=title_ids,
        status=HolidayRequestDay.Status.PENDING,
    )


def _can_decide(user, holiday_request_day):
    if user.pk == holiday_request_day.request.routed_chapter_lead_id:
        return True
    from apps.org.models import ChapterLeadAssignment

    requester_title_id = holiday_request_day.request.requester.title_id
    return ChapterLeadAssignment.objects.filter(chapter_lead=user, title_id=requester_title_id).exists()


def _units_for(day_part):
    return 1.0 if day_part == HolidayRequestDay.DayPart.FULL else 0.5


def booked_units_by_date(user, dates):
    """How much of each day `user` has already committed, as units where a
    full day is 1.0 and a 1/2 day is 0.5.

    Only pending and approved days count - refused and cancelled ones have
    released the day again.
    """
    booked = {}
    rows = HolidayRequestDay.objects.filter(
        request__requester=user,
        status__in=[HolidayRequestDay.Status.PENDING, HolidayRequestDay.Status.APPROVED],
        date__in=dates,
    ).values_list("date", "day_part")
    for day, day_part in rows:
        booked[day] = booked.get(day, 0.0) + _units_for(day_part)
    return booked


def submit_request(user, day_entries, note=""):
    """day_entries: iterable of (date, day_part) pairs, day_part one of
    HolidayRequestDay.DayPart. Validates past dates/weekends/bank-holidays/
    duplicates/how much of each day is already booked, then creates the
    request + day rows and schedules the submitted-notification email. Each
    day is approved or refused individually afterward - see approve_day/
    refuse_day."""
    day_entries = list(day_entries)
    if not day_entries:
        raise ValidationError("Select at least one day.")

    dates = [d for d, _ in day_entries]
    if len(dates) != len(set(dates)):
        raise ValidationError("Each date can only appear once in a request.")

    tribe = user.squad.tribe if user.squad else None
    bank_holidays = set()
    if tribe:
        bank_holidays = set(
            BankHoliday.objects.filter(tribe=tribe, date__in=dates).values_list("date", flat=True)
        )

    today = timezone.localdate()
    for day, _part in day_entries:
        if day < today:
            raise ValidationError(f"{day} is in the past and cannot be requested.")
        if day.weekday() >= 5:
            raise ValidationError(f"{day} is a weekend and cannot be requested.")
        if day in bank_holidays:
            raise ValidationError(f"{day} is a bank holiday and cannot be requested.")

    # A day holds 1.0 units in total, so what's already booked decides what
    # can still be added: a 1/2 day leaves room for one more 1/2 day, while
    # a full day leaves none.
    booked = booked_units_by_date(user, dates)
    for day, day_part in day_entries:
        already = booked.get(day, 0.0)
        if already + _units_for(day_part) > 1.0:
            if already >= 1.0:
                raise ValidationError(f"You already have a full day booked on {day}.")
            raise ValidationError(
                f"You already have a 1/2 day on {day} - only another 1/2 day can be added."
            )

    with transaction.atomic():
        holiday_request = HolidayRequest.objects.create(
            requester=user,
            routed_chapter_lead=resolve_chapter_lead(user),
            note=note,
        )
        HolidayRequestDay.objects.bulk_create(
            HolidayRequestDay(request=holiday_request, date=day, day_part=part)
            for day, part in day_entries
        )
        transaction.on_commit(lambda: notify_request_submitted(holiday_request))

    return holiday_request


def approve_day(holiday_request_day, decided_by):
    if holiday_request_day.status != HolidayRequestDay.Status.PENDING:
        raise ValidationError("Only a pending day can be approved.")
    if not _can_decide(decided_by, holiday_request_day):
        raise ValidationError("Only the Chapter Lead or a designated backup can decide this request.")

    holiday_request_day.status = HolidayRequestDay.Status.APPROVED
    holiday_request_day.decided_by = decided_by
    holiday_request_day.decided_at = timezone.now()
    holiday_request_day.save(update_fields=["status", "decided_by", "decided_at"])
    transaction.on_commit(lambda: notify_day_approved(holiday_request_day))
    return holiday_request_day


def refuse_day(holiday_request_day, decided_by, reason):
    if holiday_request_day.status != HolidayRequestDay.Status.PENDING:
        raise ValidationError("Only a pending day can be refused.")
    if not _can_decide(decided_by, holiday_request_day):
        raise ValidationError("Only the Chapter Lead or a designated backup can decide this request.")
    if not reason or not reason.strip():
        raise ValidationError("A justification is required to refuse a request.")

    holiday_request_day.status = HolidayRequestDay.Status.REFUSED
    holiday_request_day.decided_by = decided_by
    holiday_request_day.decided_at = timezone.now()
    holiday_request_day.decision_reason = reason.strip()
    holiday_request_day.save(update_fields=["status", "decided_by", "decided_at", "decision_reason"])
    transaction.on_commit(lambda: notify_day_refused(holiday_request_day))
    return holiday_request_day


def cancel_own_day(user, holiday_request_day):
    """A requester withdrawing one of their own days.

    Pending days are withdrawn before anyone has looked at them; approved
    days are giving back time off that was already granted, so the routed
    Chapter Lead is emailed. Either way the row is kept as CANCELLED rather
    than deleted: it leaves the date free to request again, disappears from
    the calendar and metrics, and stays visible in the Chapter Lead's
    decision board as an audit trail.
    """
    if holiday_request_day.request.requester_id != user.pk:
        raise ValidationError("You can only cancel your own holiday requests.")

    cancellable = [HolidayRequestDay.Status.PENDING, HolidayRequestDay.Status.APPROVED]
    if holiday_request_day.status not in cancellable:
        raise ValidationError(
            f"This day is already {holiday_request_day.get_status_display().lower()} "
            "and cannot be cancelled."
        )

    was_approved = holiday_request_day.status == HolidayRequestDay.Status.APPROVED
    holiday_request_day.status = HolidayRequestDay.Status.CANCELLED
    holiday_request_day.decided_by = user
    holiday_request_day.decided_at = timezone.now()
    holiday_request_day.decision_reason = "Cancelled by the requester."
    holiday_request_day.save(
        update_fields=["status", "decided_by", "decided_at", "decision_reason"]
    )

    if was_approved:
        chapter_lead = holiday_request_day.request.routed_chapter_lead
        transaction.on_commit(
            lambda: notify_approved_day_cancelled(holiday_request_day, chapter_lead)
        )
    return holiday_request_day


def cancellable_days_for(user):
    """The user's own days they may still withdraw."""
    return HolidayRequestDay.objects.filter(
        request__requester=user,
        status__in=[HolidayRequestDay.Status.PENDING, HolidayRequestDay.Status.APPROVED],
    )


def silently_set_day_status(editor, member, day_entries, comment):
    """Lets `editor` (a holder of SILENT_EDIT_PERM) directly add a full/half
    day holiday for `member`, or cancel one of their existing holidays,
    bypassing the normal submit/approve/refuse workflow entirely -
    restricted to members of editor's own squad, and never permitted
    against a Chapter Lead (the permission may only manage an ordinary
    member's own holiday, never touch whoever approves everyone else's).

    day_entries: iterable of (date, action, day_part) tuples, action one of
    "add"/"cancel" (day_part is ignored for "cancel"). Unlike the admin's
    silent-edit access, this still tells the routed Chapter Lead what
    happened afterward: a recap email plus the entry showing up as usual in
    their approval inbox's "recently decided" list, stamped with `editor`
    as decided_by.

    An existing pending/approved day for the same date is updated in place
    (rather than creating a conflicting second row) for "add"; "cancel"
    always targets an existing pending/approved day and fails if there
    isn't one.
    """
    from apps.accounts.models import User

    if editor.squad_id is None or editor.squad_id != member.squad_id:
        raise ValidationError("You can only edit holiday status for members of your own squad.")
    if member.role == User.Role.CHAPTER_LEAD:
        raise ValidationError("A Chapter Lead's holiday status can never be edited this way.")

    day_entries = list(day_entries)
    if not day_entries:
        raise ValidationError("Select at least one day.")
    if not comment or not comment.strip():
        raise ValidationError("A comment is required.")
    comment = comment.strip()

    dates = [d for d, _action, _part in day_entries]
    if len(dates) != len(set(dates)):
        raise ValidationError("Each date can only appear once.")
    for _day, action, _part in day_entries:
        if action not in ("add", "cancel"):
            raise ValidationError(f"Unknown action {action!r}.")

    add_dates = [day for day, action, _part in day_entries if action == "add"]
    tribe = member.squad.tribe if member.squad else None
    bank_holidays = set()
    if tribe and add_dates:
        bank_holidays = set(
            BankHoliday.objects.filter(tribe=tribe, date__in=add_dates).values_list("date", flat=True)
        )
    for day in add_dates:
        if day.weekday() >= 5:
            raise ValidationError(f"{day} is a weekend and cannot be edited.")
        if day in bank_holidays:
            raise ValidationError(f"{day} is a bank holiday and cannot be edited.")

    now = timezone.now()
    touched_days = []
    with transaction.atomic():
        existing_by_date = {
            d.date: d
            for d in HolidayRequestDay.objects.filter(request__requester=member, date__in=dates).exclude(
                status__in=[HolidayRequestDay.Status.REFUSED, HolidayRequestDay.Status.CANCELLED]
            )
        }
        for day, action, _part in day_entries:
            if action == "cancel" and day not in existing_by_date:
                raise ValidationError(f"There is no existing holiday on {day} to cancel.")

        new_dates = [
            (day, part) for day, action, part in day_entries if action == "add" and day not in existing_by_date
        ]
        holiday_request = None
        if new_dates:
            holiday_request = HolidayRequest.objects.create(
                requester=member,
                routed_chapter_lead=resolve_chapter_lead(member),
                note=f"Recorded by {editor} via the squad calendar.",
            )

        for day, action, part in day_entries:
            existing = existing_by_date.get(day)
            new_status = (
                HolidayRequestDay.Status.APPROVED if action == "add" else HolidayRequestDay.Status.CANCELLED
            )
            if existing:
                if action == "add":
                    existing.day_part = part
                existing.status = new_status
                existing.decided_by = editor
                existing.decided_at = now
                existing.decision_reason = comment
                existing.save(
                    update_fields=["day_part", "status", "decided_by", "decided_at", "decision_reason"]
                )
                touched_days.append(existing)
            else:
                touched_days.append(
                    HolidayRequestDay.objects.create(
                        request=holiday_request,
                        date=day,
                        day_part=part,
                        status=new_status,
                        decided_by=editor,
                        decided_at=now,
                        decision_reason=comment,
                    )
                )

        chapter_lead = resolve_chapter_lead(member)
        transaction.on_commit(
            lambda: notify_silent_edit(editor, member, chapter_lead, touched_days, comment)
        )

    return touched_days


def _weekday_subranges(start, end):
    """Split [start, end] (inclusive) into contiguous (sub_start, sub_end)
    weekday-only date pairs, breaking at each weekend. Used to keep Sprint
    background events off Saturday/Sunday even though a sprint's overall
    date range (Monday through the following Friday) spans a weekend in
    between - splitting the underlying event data is robust regardless of
    how FullCalendar happens to render multi-day background segments,
    unlike trying to mask it with CSS alone."""
    subranges = []
    range_start = None
    last_weekday = None
    day = start
    while day <= end:
        if day.weekday() < 5:
            if range_start is None:
                range_start = day
            last_weekday = day
        elif range_start is not None:
            subranges.append((range_start, last_weekday))
            range_start = None
        day += timedelta(days=1)
    if range_start is not None:
        subranges.append((range_start, last_weekday))
    return subranges


def calendar_feed_events(squad, start, end):
    """FullCalendar-shaped event dicts for a squad's calendar: member
    absences (pending/approved), sprints, bank holidays, and events visible
    at squad/cluster/tribe scope."""
    from apps.calendar_data.models import BankHoliday, Event, Sprint

    tribe = squad.tribe
    cluster = squad.cluster
    events = []

    day_rows = HolidayRequestDay.objects.filter(
        request__requester__squad=squad,
        date__gte=start,
        date__lte=end,
        status__in=[HolidayRequestDay.Status.PENDING, HolidayRequestDay.Status.APPROVED],
    ).select_related("request", "request__requester")
    for day in day_rows:
        req = day.request
        events.append(
            {
                "id": f"holiday-{day.pk}",
                # "Nina Kovac - 1/2 day" rather than parenthesised: the chips
                # are narrow and often truncate, and a trailing "(1/2 day"
                # with no closing bracket reads worse than a clipped dash.
                "title": f"{req.requester} - {day.get_day_part_display()}",
                "start": day.date.isoformat(),
                "allDay": True,
                # Palette matches the page legend in squad_calendar.html.
                "color": "#21764a" if day.status == HolidayRequestDay.Status.APPROVED else "#e0a02a",
                "extendedProps": {
                    "type": "holiday",
                    "status": day.status,
                    "dayPart": day.day_part,
                    "titleCode": req.requester.title_id,
                    # Lets the squad calendar's silent-edit panel look up a
                    # specific member's current day_part for a clicked date
                    # (see squad_calendar.html) without a separate request.
                    "requesterId": req.requester_id,
                },
            }
        )

    for sprint in Sprint.objects.filter(tribe=tribe, start_date__lte=end, end_date__gte=start):
        for i, (sub_start, sub_end) in enumerate(_weekday_subranges(sprint.start_date, sprint.end_date)):
            events.append(
                {
                    "id": f"sprint-{sprint.pk}-{i}",
                    "title": sprint.display_label,
                    "start": sub_start.isoformat(),
                    "end": (sub_end + timedelta(days=1)).isoformat(),
                    "display": "background",
                    "color": "#eaf1fb",
                }
            )

    for bh in BankHoliday.objects.filter(tribe=tribe, date__gte=start, date__lte=end):
        events.append(
            {
                "id": f"bankholiday-{bh.pk}",
                "title": bh.name,
                "start": bh.date.isoformat(),
                "allDay": True,
                "color": "#c0392f",
                "extendedProps": {"type": "bankholiday"},
            }
        )

    scope_q = (
        Q(scope=Event.Scope.TRIBE)
        | Q(scope=Event.Scope.CLUSTER, cluster=cluster)
        | Q(scope=Event.Scope.SQUAD, squad=squad)
    )
    for ev in Event.objects.filter(scope_q, tribe=tribe, start_date__lte=end, end_date__gte=start):
        events.append(
            {
                "id": f"event-{ev.pk}",
                "title": ev.name,
                "start": ev.start_date.isoformat(),
                "end": (ev.end_date + timedelta(days=1)).isoformat(),
                "allDay": True,
                "color": "#7b3fa0",
                "extendedProps": {"type": "event"},
            }
        )

    return events
