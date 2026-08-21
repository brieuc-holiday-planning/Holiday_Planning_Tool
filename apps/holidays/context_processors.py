def approver_flag(request):
    """Exposes whether the current user can act as an approver (primary
    Chapter Lead or backup) so base.html can show the Approval inbox link -
    that's no longer tied to role=Chapter Lead alone, since any user can be
    designated a backup approver."""
    if not request.user.is_authenticated:
        return {"user_is_approver": False}

    from . import services

    return {"user_is_approver": services.is_approver(request.user)}
