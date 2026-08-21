from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

# Django's own defaults ("Django administration") would otherwise show above
# the app's branding in templates/admin/base_site.html.
admin.site.site_header = "Holiday Planning Tool"
admin.site.site_title = "Holiday Planning Tool admin"
admin.site.index_title = "Tribe administration"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="accounts:landing"), name="root"),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("", include("apps.holidays.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
]
