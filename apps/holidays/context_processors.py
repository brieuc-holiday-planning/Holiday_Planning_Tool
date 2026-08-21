def approver_flag(request):
    """Exposes whether the current user can act as an approver, and how many
    days are waiting on them, so the nav can show the Approval inbox link
    with a pending-count badge on every page.

    The count query only runs for actual approvers - everyone else short-
    circuits on the flag.
    """
    if not request.user.is_authenticated:
        return {"user_is_approver": False, "pending_approval_count": 0}

    from . import services

    is_approver = services.is_approver(request.user)
    return {
        "user_is_approver": is_approver,
        "pending_approval_count": (
            services.pending_days_for(request.user).count() if is_approver else 0
        ),
    }
