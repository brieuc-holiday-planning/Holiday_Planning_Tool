def sync_is_staff(user, *, silent_edit=None):
    """Recomputes is_staff from the current rules - superuser, an
    admin-granting title (org.Title.grants_admin_access, see
    User.is_scrum_master), or holding the silent-edit permission - and
    saves only if it actually changed. `silent_edit` lets a caller that
    already knows the intended value (e.g. UserAdmin, mid-form-save) pass
    it explicitly instead of relying on has_perm, which would otherwise
    need the M2M change already committed."""
    if silent_edit is None:
        silent_edit = user.has_perm("holidays.edit_any_holiday_silently")
    correct = user.is_superuser or user.is_scrum_master or silent_edit
    if user.is_staff != correct:
        user.is_staff = correct
        user.save(update_fields=["is_staff"])
    return correct


def member_counts_by_title(members, tribe):
    """One entry per Title defined for `tribe` (including zero counts), for
    the given iterable of members. Used for squad/cluster composition
    summaries and per-day working-count displays."""
    from apps.org.models import Title

    counts = {}
    for member in members:
        counts[member.title_id] = counts.get(member.title_id, 0) + 1

    titles = Title.objects.filter(tribe=tribe) if tribe else Title.objects.none()
    return [
        {
            "code": title.pk,
            "label": title.name,
            "abbreviation": title.abbreviation,
            "total": counts.get(title.pk, 0),
        }
        for title in titles
    ]
