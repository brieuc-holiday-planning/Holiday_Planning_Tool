from django.test import TestCase

from apps.org.models import Cluster, Squad, Tribe
from apps.org.services import clusters_with_squads


class ClustersWithSquadsTests(TestCase):
    def setUp(self):
        self.tribe = Tribe.objects.create(name="Tribe A")
        self.cluster_a = Cluster.objects.create(tribe=self.tribe, name="Cluster A")
        self.cluster_b = Cluster.objects.create(tribe=self.tribe, name="Cluster B")
        self.squad_a1 = Squad.objects.create(cluster=self.cluster_a, name="Squad A1")
        self.squad_a2 = Squad.objects.create(cluster=self.cluster_a, name="Squad A2")
        self.squad_b1 = Squad.objects.create(cluster=self.cluster_b, name="Squad B1")

    def test_nests_squads_under_their_cluster(self):
        result = clusters_with_squads(self.tribe, "holidays:squad_calendar")
        by_cluster = {c["name"]: [s["name"] for s in c["squads"]] for c in result}
        self.assertEqual(by_cluster["Cluster A"], ["Squad A1", "Squad A2"])
        self.assertEqual(by_cluster["Cluster B"], ["Squad B1"])

    def test_squad_urls_point_to_the_given_view(self):
        result = clusters_with_squads(self.tribe, "holidays:squad_calendar")
        squad_a1 = next(s for c in result for s in c["squads"] if s["name"] == "Squad A1")
        self.assertEqual(squad_a1["url"], f"/squads/{self.squad_a1.id}/calendar/")

    def test_different_url_name_for_dashboard(self):
        result = clusters_with_squads(self.tribe, "dashboard:squad_dashboard")
        squad_a1 = next(s for c in result for s in c["squads"] if s["name"] == "Squad A1")
        self.assertEqual(squad_a1["url"], f"/dashboard/squads/{self.squad_a1.id}/")

    def test_excludes_other_tribes(self):
        other_tribe = Tribe.objects.create(name="Tribe B")
        Cluster.objects.create(tribe=other_tribe, name="Cluster C")
        result = clusters_with_squads(self.tribe, "holidays:squad_calendar")
        self.assertEqual({c["name"] for c in result}, {"Cluster A", "Cluster B"})
