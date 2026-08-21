from django.urls import reverse

from .models import Cluster


def clusters_with_squads(tribe, url_name):
    """Nested [{id, name, squads: [{id, name, url}, ...]}] for every
    cluster/squad in `tribe`, used to build a cluster -> squad cascading
    picker. `url_name` is reversed with the squad's id to link straight to
    that squad's page (e.g. "holidays:squad_calendar" or
    "dashboard:squad_dashboard")."""
    clusters = Cluster.objects.filter(tribe=tribe).prefetch_related("squads").order_by("name")
    return [
        {
            "id": cluster.id,
            "name": cluster.name,
            "squads": [
                {"id": squad.id, "name": squad.name, "url": reverse(url_name, args=[squad.id])}
                for squad in cluster.squads.all().order_by("name")
            ],
        }
        for cluster in clusters
    ]
