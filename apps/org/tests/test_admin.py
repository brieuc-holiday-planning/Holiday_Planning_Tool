from django.test import TestCase

from apps.accounts.models import User
from apps.org.models import Cluster, Squad, Tribe
from apps.org.titles import seed_default_titles


class TitleAdminGrantsAdminAccessResyncTests(TestCase):
    """Toggling Title.grants_admin_access in the admin must resync is_staff
    for everyone holding that title - a User admin save resyncs its own
    row automatically, but editing the Title itself doesn't touch those
    User rows unless TitleAdmin.save_model does it explicitly."""

    def setUp(self):
        tribe = Tribe.objects.create(name="Tribe A")
        cluster = Cluster.objects.create(tribe=tribe, name="Cluster A")
        squad = Squad.objects.create(cluster=cluster, name="Squad A")
        self.titles = seed_default_titles(tribe)

        self.superuser = User.objects.create_superuser(
            username="root", password="pass1234", title=self.titles["scrum_master"]
        )
        self.member = User.objects.create_user(
            username="eu1", password="pass1234", title=self.titles["business_analyst"], squad=squad
        )
        self.assertFalse(self.member.is_staff)

    def _title_change_payload(self, title, **overrides):
        payload = {
            "tribe": title.tribe_id,
            "name": title.name,
            "abbreviation": title.abbreviation,
            "_save": "Save",
        }
        payload.update(overrides)
        return payload

    def test_granting_admin_access_promotes_every_holder(self):
        self.client.login(username="root", password="pass1234")
        title = self.titles["business_analyst"]
        response = self.client.post(
            f"/admin/org/title/{title.pk}/change/",
            self._title_change_payload(title, grants_admin_access="on"),
        )
        self.assertEqual(response.status_code, 302)

        self.member.refresh_from_db()
        self.assertTrue(self.member.is_staff)
        self.assertTrue(self.member.is_scrum_master)

    def test_revoking_admin_access_demotes_every_holder(self):
        self.client.login(username="root", password="pass1234")
        scrum_master_title = self.titles["scrum_master"]
        admin_user = User.objects.create_user(
            username="eu2", password="pass1234", title=scrum_master_title
        )
        self.assertTrue(admin_user.is_staff)

        response = self.client.post(
            f"/admin/org/title/{scrum_master_title.pk}/change/",
            self._title_change_payload(scrum_master_title),  # checkbox omitted = unchecked
        )
        self.assertEqual(response.status_code, 302)

        admin_user.refresh_from_db()
        self.assertFalse(admin_user.is_staff)
        self.assertFalse(admin_user.is_scrum_master)
