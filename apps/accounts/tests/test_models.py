from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.accounts.models import User
from apps.org.models import Cluster, Squad, Tribe
from apps.org.titles import seed_default_titles


class UserSquadRequirementTests(TestCase):
    def setUp(self):
        tribe = Tribe.objects.create(name="Tribe A")
        cluster = Cluster.objects.create(tribe=tribe, name="Cluster A")
        self.squad = Squad.objects.create(cluster=cluster, name="Squad A")
        self.titles = seed_default_titles(tribe)

    def test_admin_title_holder_may_have_no_squad(self):
        user = User(username="sm1", title=self.titles["scrum_master"])
        user.full_clean(exclude=["password"])  # should not raise

    def test_chapter_lead_may_have_no_squad(self):
        user = User(username="lead1", role=User.Role.CHAPTER_LEAD, title=self.titles["business_analyst"])
        user.full_clean(exclude=["password"])  # should not raise

    def test_end_user_without_squad_rejected_by_clean(self):
        user = User(username="eu1", role=User.Role.END_USER, title=self.titles["data_scientist"])
        with self.assertRaises(ValidationError):
            user.clean()

    def test_end_user_without_squad_not_blocked_at_db_level(self):
        # Squad-requiredness is enforced by clean()/full_clean() (see
        # test_end_user_without_squad_rejected_by_clean above), not a DB
        # constraint - the "who's exempt" rule now depends on
        # title.grants_admin_access, a cross-table condition a
        # CheckConstraint can't express. Every write path that matters
        # (admin forms, ModelForm) calls full_clean(), but a bare
        # create_user() bypassing it isn't blocked by the DB itself.
        user = User.objects.create_user(
            username="eu2", role=User.Role.END_USER, title=self.titles["data_scientist"]
        )
        self.assertIsNone(user.squad)

    def test_end_user_with_squad_saves(self):
        user = User.objects.create_user(
            username="eu3", role=User.Role.END_USER, title=self.titles["data_scientist"], squad=self.squad
        )
        self.assertEqual(user.squad, self.squad)


class OneChapterLeadPerTitleTests(TestCase):
    """Assigning role=Chapter Lead + a title is how someone becomes THE
    validator for that title (see holidays.services.resolve_chapter_lead) -
    a DB constraint keeps that mapping unambiguous."""

    def setUp(self):
        tribe = Tribe.objects.create(name="Tribe A")
        cluster = Cluster.objects.create(tribe=tribe, name="Cluster A")
        self.squad = Squad.objects.create(cluster=cluster, name="Squad A")
        self.titles = seed_default_titles(tribe)

    def test_second_chapter_lead_for_same_title_rejected(self):
        User.objects.create_user(
            username="lead1", role=User.Role.CHAPTER_LEAD, title=self.titles["business_analyst"], squad=self.squad
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(
                username="lead2",
                role=User.Role.CHAPTER_LEAD,
                title=self.titles["business_analyst"],
                squad=self.squad,
            )

    def test_different_titles_can_each_have_a_chapter_lead(self):
        User.objects.create_user(
            username="lead1", role=User.Role.CHAPTER_LEAD, title=self.titles["business_analyst"], squad=self.squad
        )
        User.objects.create_user(
            username="lead2", role=User.Role.CHAPTER_LEAD, title=self.titles["data_scientist"], squad=self.squad
        )  # should not raise

    def test_end_users_with_the_same_title_are_unrestricted(self):
        User.objects.create_user(
            username="eu1", role=User.Role.END_USER, title=self.titles["data_scientist"], squad=self.squad
        )
        User.objects.create_user(
            username="eu2", role=User.Role.END_USER, title=self.titles["data_scientist"], squad=self.squad
        )  # should not raise - the constraint only applies to Chapter Leads


class TitleDrivenAdminAccessTests(TestCase):
    """There's no Role.SCRUM_MASTER anymore - admin access (is_scrum_master
    / is_staff) is purely a function of the user's title (see org.Title.
    grants_admin_access), independent of `role`."""

    def setUp(self):
        tribe = Tribe.objects.create(name="Tribe A")
        cluster = Cluster.objects.create(tribe=tribe, name="Cluster A")
        self.squad = Squad.objects.create(cluster=cluster, name="Squad A")
        self.titles = seed_default_titles(tribe)

    def test_admin_title_grants_is_scrum_master_regardless_of_role(self):
        chapter_lead_admin = User.objects.create_user(
            username="lead-sm", role=User.Role.CHAPTER_LEAD, title=self.titles["scrum_master"]
        )
        end_user_admin = User.objects.create_user(
            username="eu-sm", role=User.Role.END_USER, title=self.titles["scrum_master"]
        )
        self.assertTrue(chapter_lead_admin.is_scrum_master)
        self.assertTrue(end_user_admin.is_scrum_master)

    def test_non_admin_title_is_not_scrum_master(self):
        user = User.objects.create_user(
            username="eu1", role=User.Role.END_USER, title=self.titles["data_scientist"], squad=self.squad
        )
        self.assertFalse(user.is_scrum_master)

    def test_admin_title_auto_elevates_is_staff_on_save(self):
        user = User.objects.create_user(username="eu-sm", title=self.titles["scrum_master"])
        self.assertTrue(user.is_staff)
