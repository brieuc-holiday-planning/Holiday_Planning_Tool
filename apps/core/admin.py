class ScrumMasterOnlyAdminMixin:
    """Restricts a ModelAdmin to admins of the app - anyone whose title
    grants admin access (see accounts.User.is_scrum_master) - plus the
    break-glass Django superuser. These admins are is_staff but never
    is_superuser, so this check is explicit rather than relying on
    Django's has_perm bypass."""

    def _is_scrum_master(self, request):
        user = request.user
        return user.is_superuser or (user.is_authenticated and user.is_scrum_master)

    def has_view_permission(self, request, obj=None):
        return self._is_scrum_master(request)

    def has_add_permission(self, request):
        return self._is_scrum_master(request)

    def has_change_permission(self, request, obj=None):
        return self._is_scrum_master(request)

    def has_delete_permission(self, request, obj=None):
        return self._is_scrum_master(request)

    def has_module_permission(self, request):
        return self._is_scrum_master(request)


class ReadOnlyForEveryoneAdminMixin(ScrumMasterOnlyAdminMixin):
    """View-only in admin: add/change/delete always denied, even for Scrum
    Masters, because writes must go through the app's own workflow views so
    side effects (like decision emails) actually fire."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
