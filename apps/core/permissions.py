from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied


def role_required(*roles):
    """View decorator restricting access to users whose .role is in `roles`."""

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapped(request, *args, **kwargs):
            if request.user.role not in roles:
                raise PermissionDenied("You do not have access to this page.")
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


class RoleRequiredMixin(AccessMixin):
    """CBV mixin restricting access to users whose .role is in allowed_roles.

    Built on AccessMixin (not LoginRequiredMixin) so this can override
    dispatch() once, doing the login check and the role check before handing
    off to the real view's dispatch — subclassing LoginRequiredMixin here
    would require calling its dispatch too, redoing the auth check.
    """

    allowed_roles: tuple = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if self.allowed_roles and request.user.role not in self.allowed_roles:
            raise PermissionDenied("You do not have access to this page.")
        return super().dispatch(request, *args, **kwargs)
