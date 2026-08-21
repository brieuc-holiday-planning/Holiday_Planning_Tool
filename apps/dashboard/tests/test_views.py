from django.test import TestCase

from apps.accounts.models import User
from apps.org.models import Cluster, Squad, Tribe
from apps.org.titles import seed_default_titles


class DashboardVisibilityTests(TestCase):
    """Squad/cluster metrics are viewable tribe-wide by any authenticated
    user, regardless of role - same open-viewing model as the squad
    calendar. There is no analogous "write" action on this page (unlike
    holiday requests, which are still squad-restricted to submit), so
    there's nothing left to gate here."""

    def setUp(self):
        tribe = Tribe.objects.create(name="Tribe A")
        self.cluster = Cluster.objects.create(tribe=tribe, name="Cluster A")
        self.squad_a = Squad.objects.create(cluster=self.cluster, name="Squad A")
        self.squad_b = Squad.objects.create(cluster=self.cluster, name="Squad B")
        self.titles = seed_default_titles(tribe)

        self.scrum_master = User.objects.create_user(
            username="sm1", password="pass1234", title=self.titles["scrum_master"]
        )
        self.chapter_lead = User.objects.create_user(
            username="lead1",
            password="pass1234",
            role=User.Role.CHAPTER_LEAD,
            title=self.titles["data_scientist"],
            squad=self.squad_a,
        )
        self.end_user_a = User.objects.create_user(
            username="eua",
            password="pass1234",
            role=User.Role.END_USER,
            title=self.titles["data_scientist"],
            squad=self.squad_a,
        )

    def test_end_user_can_view_own_squad_dashboard(self):
        self.client.login(username="eua", password="pass1234")
        response = self.client.get(f"/dashboard/squads/{self.squad_a.id}/")
        self.assertEqual(response.status_code, 200)

    def test_end_user_can_view_other_squads_dashboard_too(self):
        self.client.login(username="eua", password="pass1234")
        response = self.client.get(f"/dashboard/squads/{self.squad_b.id}/")
        self.assertEqual(response.status_code, 200)

    def test_end_user_can_view_own_cluster_dashboard(self):
        self.client.login(username="eua", password="pass1234")
        response = self.client.get(f"/dashboard/clusters/{self.cluster.id}/")
        self.assertEqual(response.status_code, 200)

    def test_chapter_lead_can_view_any_squad_dashboard(self):
        self.client.login(username="lead1", password="pass1234")
        response = self.client.get(f"/dashboard/squads/{self.squad_b.id}/")
        self.assertEqual(response.status_code, 200)

    def test_scrum_master_can_view_any_squad_dashboard(self):
        self.client.login(username="sm1", password="pass1234")
        response = self.client.get(f"/dashboard/squads/{self.squad_b.id}/")
        self.assertEqual(response.status_code, 200)

    def test_squad_picker_lists_every_squad_in_the_tribe_for_any_role(self):
        self.client.login(username="eua", password="pass1234")
        response = self.client.get(f"/dashboard/squads/{self.squad_a.id}/")
        self.assertContains(response, self.squad_a.name)
        self.assertContains(response, self.squad_b.name)
        self.assertContains(response, self.cluster.name)

    def test_every_squad_option_carries_the_data_attributes_the_picker_needs(self):
        # cluster_squad_picker.js filters squad options by data-cluster and
        # navigates using data-url; without both on every option, switching
        # cluster silently leaves the page on the previous squad.
        self.client.login(username="eua", password="pass1234")
        response = self.client.get(f"/dashboard/squads/{self.squad_a.id}/")
        for squad in [self.squad_a, self.squad_b]:
            self.assertContains(
                response,
                f'data-cluster="{squad.cluster_id}" data-url="/dashboard/squads/{squad.id}/"',
            )

    def test_squad_metrics_page_has_no_calendar(self):
        self.client.login(username="eua", password="pass1234")
        response = self.client.get(f"/dashboard/squads/{self.squad_a.id}/")
        self.assertNotContains(response, "FullCalendar")
        self.assertNotContains(response, 'id="calendar"')
