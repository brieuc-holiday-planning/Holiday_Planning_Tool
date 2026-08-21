from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.accounts.services import member_counts_by_title
from apps.org.models import Cluster, Squad
from apps.org.services import clusters_with_squads

from . import services


@login_required
def squad_dashboard(request, squad_id):
    # Any authenticated user can view any squad's metrics across the whole
    # tribe, same as the squad calendar.
    squad = get_object_or_404(Squad, pk=squad_id)
    year = int(request.GET.get("year", date.today().year))
    members, metrics = services.compute_squad_metrics(squad, year)
    rows = [(member, metrics[member.pk]) for member in members]
    return render(
        request,
        "dashboard/squad_dashboard.html",
        {
            "squad": squad,
            "year": year,
            "rows": rows,
            "title_totals": member_counts_by_title(members, squad.tribe),
            "clusters_with_squads": clusters_with_squads(squad.tribe, "dashboard:squad_dashboard"),
        },
    )


@login_required
def cluster_dashboard(request, cluster_id):
    cluster = get_object_or_404(Cluster, pk=cluster_id)
    year = int(request.GET.get("year", date.today().year))
    members, metrics = services.compute_cluster_metrics(cluster, year)
    rows = [(member, metrics[member.pk]) for member in members]
    return render(
        request,
        "dashboard/cluster_dashboard.html",
        {
            "cluster": cluster,
            "year": year,
            "rows": rows,
            "title_totals": member_counts_by_title(members, cluster.tribe),
            "visible_clusters": Cluster.objects.filter(tribe=cluster.tribe).order_by("name"),
        },
    )
