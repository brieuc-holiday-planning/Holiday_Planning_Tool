from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("squads/<int:squad_id>/", views.squad_dashboard, name="squad_dashboard"),
    path("clusters/<int:cluster_id>/", views.cluster_dashboard, name="cluster_dashboard"),
]
