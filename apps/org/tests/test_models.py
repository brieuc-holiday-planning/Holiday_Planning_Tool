from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.accounts.models import User
from apps.org.models import ChapterLeadAssignment, Cluster, Squad, Title, Tribe
from apps.org.titles import seed_default_titles


class OrgHierarchyTests(TestCase):
    def setUp(self):
        self.tribe = Tribe.objects.create(name="Tribe A")
        self.cluster = Cluster.objects.create(tribe=self.tribe, name="Cluster A")
        self.squad = Squad.objects.create(cluster=self.cluster, name="Squad A")

    def test_squad_exposes_tribe_through_cluster(self):
        self.assertEqual(self.squad.tribe, self.tribe)

    def test_duplicate_cluster_name_within_tribe_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Cluster.objects.create(tribe=self.tribe, name="Cluster A")

    def test_duplicate_squad_name_within_cluster_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Squad.objects.create(cluster=self.cluster, name="Squad A")

    def test_same_cluster_name_allowed_in_different_tribe(self):
        other_tribe = Tribe.objects.create(name="Tribe B")
        Cluster.objects.create(tribe=other_tribe, name="Cluster A")  # should not raise


class TitleModelTests(TestCase):
    """Titles are entirely admin-managed per tribe, not limited to any
    fixed list - an admin can add arbitrary new ones with their own
    abbreviation."""

    def setUp(self):
        self.tribe = Tribe.objects.create(name="Tribe A")

    def test_arbitrary_new_title_can_be_created(self):
        title = Title.objects.create(tribe=self.tribe, name="Site Reliability Engineer", abbreviation="SRE")
        self.assertEqual(title.name, "Site Reliability Engineer")

    def test_duplicate_name_within_tribe_rejected(self):
        Title.objects.create(tribe=self.tribe, name="Data Scientist", abbreviation="DS")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Title.objects.create(tribe=self.tribe, name="Data Scientist", abbreviation="DS2")

    def test_duplicate_abbreviation_within_tribe_rejected(self):
        Title.objects.create(tribe=self.tribe, name="Data Scientist", abbreviation="DS")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Title.objects.create(tribe=self.tribe, name="Design Specialist", abbreviation="DS")

    def test_same_name_allowed_in_different_tribe(self):
        Title.objects.create(tribe=self.tribe, name="Data Scientist", abbreviation="DS")
        other_tribe = Tribe.objects.create(name="Tribe B")
        Title.objects.create(tribe=other_tribe, name="Data Scientist", abbreviation="DS")  # should not raise

    def test_seed_default_titles_creates_five_and_is_idempotent(self):
        titles = seed_default_titles(self.tribe)
        self.assertEqual(len(titles), 5)
        self.assertEqual(Title.objects.filter(tribe=self.tribe).count(), 5)
        seed_default_titles(self.tribe)  # re-running should not duplicate
        self.assertEqual(Title.objects.filter(tribe=self.tribe).count(), 5)


class ChapterLeadAssignmentTests(TestCase):
    """ChapterLeadAssignment represents *backup* approvers only - the
    primary Chapter Lead for a title is whoever has role=Chapter Lead and
    that title on their User record (see accounts.User's
    one_chapter_lead_per_title constraint), assigned via the User admin."""

    def setUp(self):
        self.tribe = Tribe.objects.create(name="Tribe A")
        self.cluster = Cluster.objects.create(tribe=self.tribe, name="Cluster A")
        self.squad = Squad.objects.create(cluster=self.cluster, name="Squad A")
        self.titles = seed_default_titles(self.tribe)
        self.data_scientist = self.titles["data_scientist"]
        self.lead = User.objects.create_user(
            username="lead1",
            role=User.Role.CHAPTER_LEAD,
            title=self.data_scientist,
            squad=self.squad,
        )

    def test_multiple_backups_allowed_for_the_same_title(self):
        backup1 = User.objects.create_user(
            username="backup1", role=User.Role.END_USER, title=self.data_scientist, squad=self.squad
        )
        backup2 = User.objects.create_user(
            username="backup2", role=User.Role.END_USER, title=self.data_scientist, squad=self.squad
        )
        ChapterLeadAssignment.objects.create(tribe=self.tribe, title=self.data_scientist, chapter_lead=backup1)
        ChapterLeadAssignment.objects.create(
            tribe=self.tribe, title=self.data_scientist, chapter_lead=backup2
        )  # should not raise - several backups per title are allowed

    def test_same_backup_twice_for_same_title_rejected(self):
        backup = User.objects.create_user(
            username="backup1", role=User.Role.END_USER, title=self.data_scientist, squad=self.squad
        )
        ChapterLeadAssignment.objects.create(tribe=self.tribe, title=self.data_scientist, chapter_lead=backup)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ChapterLeadAssignment.objects.create(tribe=self.tribe, title=self.data_scientist, chapter_lead=backup)

    def test_any_role_can_be_designated_a_backup(self):
        end_user = User.objects.create_user(
            username="enduser1",
            role=User.Role.END_USER,
            title=self.data_scientist,
            squad=self.squad,
        )
        assignment = ChapterLeadAssignment(
            tribe=self.tribe, title=self.data_scientist, chapter_lead=end_user
        )
        assignment.clean()  # should not raise - backups aren't restricted by role

    def test_title_from_different_tribe_rejected_by_clean(self):
        other_tribe = Tribe.objects.create(name="Tribe B")
        other_titles = seed_default_titles(other_tribe)
        assignment = ChapterLeadAssignment(
            tribe=self.tribe, title=other_titles["data_scientist"], chapter_lead=self.lead
        )
        with self.assertRaises(ValidationError):
            assignment.clean()
