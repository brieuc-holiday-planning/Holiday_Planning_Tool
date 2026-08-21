from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def _send(subject, template_base, context, to):
    if not to:
        return
    text_body = render_to_string(f"emails/{template_base}.txt", context)
    html_body = render_to_string(f"emails/{template_base}.html", context)
    message = EmailMultiAlternatives(subject=subject, body=text_body, to=list(to))
    message.attach_alternative(html_body, "text/html")
    message.send()


def notify_request_submitted(holiday_request):
    context = {"holiday_request": holiday_request}
    to = []
    if holiday_request.routed_chapter_lead and holiday_request.routed_chapter_lead.email:
        to.append(holiday_request.routed_chapter_lead.email)
    _send(
        subject=f"Holiday request from {holiday_request.requester} needs your approval",
        template_base="request_submitted",
        context=context,
        to=to,
    )

    squad = holiday_request.requester.squad
    watcher_emails = list(squad.watchers.values_list("email", flat=True)) if squad else []
    if watcher_emails:
        _send(
            subject=f"Holiday request submitted by {holiday_request.requester}",
            template_base="request_submitted_watcher",
            context=context,
            to=watcher_emails,
        )


def notify_day_approved(holiday_request_day):
    requester = holiday_request_day.request.requester
    _send(
        subject=f"Your {holiday_request_day.date} holiday request was approved",
        template_base="day_approved",
        context={"day": holiday_request_day},
        to=[requester.email] if requester.email else [],
    )


def notify_day_refused(holiday_request_day):
    requester = holiday_request_day.request.requester
    _send(
        subject=f"Your {holiday_request_day.date} holiday request was refused",
        template_base="day_refused",
        context={"day": holiday_request_day},
        to=[requester.email] if requester.email else [],
    )


def notify_silent_edit(editor, member, chapter_lead, days, comment):
    """Recap sent to the routed Chapter Lead whenever someone with the
    silent-edit permission directly sets a squad member's day status from
    the squad calendar - they aren't asked to approve anything (the
    decision is already made), just kept informed."""
    to = [chapter_lead.email] if chapter_lead and chapter_lead.email else []
    _send(
        subject=f"{editor} updated {member}'s holiday status",
        template_base="silent_edit_recap",
        context={"editor": editor, "member": member, "days": days, "comment": comment},
        to=to,
    )
