from django.urls import path

from . import views

app_name = "holidays"

urlpatterns = [
    path("squads/<int:squad_id>/calendar/", views.squad_calendar, name="squad_calendar"),
    path("squads/<int:squad_id>/calendar-feed/", views.calendar_feed, name="calendar_feed"),
    path("squads/<int:squad_id>/requests/submit/", views.submit_request, name="submit_request"),
    path("squads/<int:squad_id>/silent-edit/", views.silent_edit_status, name="silent_edit_status"),
    path("approvals/", views.approval_inbox, name="approval_inbox"),
    path("approvals/days/<int:day_id>/approve/", views.approve_day, name="approve_day"),
    path("approvals/days/<int:day_id>/refuse/", views.refuse_day, name="refuse_day"),
]
