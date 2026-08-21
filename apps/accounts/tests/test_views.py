from django.test import TestCase

from apps.accounts.models import User
from apps.org.models import Cluster, Squad, Tribe
from apps.org.titles import seed_default_titles


class RootUrlTests(TestCase):
    def test_anonymous_root_redirects_to_login(self):
        response = self.client.get("/", follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, "/accounts/login/?next=/accounts/")

    def test_authenticated_end_user_root_redirects_to_own_squad_calendar(self):
        tribe = Tribe.objects.create(name="Tribe A")
        cluster = Cluster.objects.create(tribe=tribe, name="Cluster A")
        squad = Squad.objects.create(cluster=cluster, name="Squad A")
        titles = seed_default_titles(tribe)
        User.objects.create_user(
            username="eu1",
            password="pass1234",
            role=User.Role.END_USER,
            title=titles["data_scientist"],
            squad=squad,
        )
        self.client.login(username="eu1", password="pass1234")
        response = self.client.get("/", follow=True)
        self.assertRedirects(response, f"/squads/{squad.id}/calendar/")
