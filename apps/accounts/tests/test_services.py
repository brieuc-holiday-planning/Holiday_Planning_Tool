from django.test import TestCase

from apps.accounts.models import User
from apps.accounts.services import member_counts_by_title
from apps.org.models import Cluster, Squad, Title, Tribe
from apps.org.titles import seed_default_titles


class MemberCountsByTitleTests(TestCase):
    def setUp(self):
        self.tribe = Tribe.objects.create(name="Tribe A")
        cluster = Cluster.objects.create(tribe=self.tribe, name="Cluster A")
        self.squad = Squad.objects.create(cluster=cluster, name="Squad A")
        self.titles = seed_default_titles(self.tribe)

    def test_counts_include_every_title_even_at_zero(self):
        User.objects.create_user(
            username="ds1", role=User.Role.END_USER, title=self.titles["data_scientist"], squad=self.squad
        )
        User.objects.create_user(
            username="ds2", role=User.Role.END_USER, title=self.titles["data_scientist"], squad=self.squad
        )
        User.objects.create_user(
            username="po1", role=User.Role.END_USER, title=self.titles["product_owner"], squad=self.squad
        )

        result = member_counts_by_title(self.squad.members.all(), self.tribe)
        by_code = {r["code"]: r["total"] for r in result}

        self.assertEqual(by_code[self.titles["data_scientist"].pk], 2)
        self.assertEqual(by_code[self.titles["product_owner"].pk], 1)
        self.assertEqual(by_code[self.titles["ai_engineer"].pk], 0)
        self.assertEqual(by_code[self.titles["scrum_master"].pk], 0)
        self.assertEqual(by_code[self.titles["business_analyst"].pk], 0)
        self.assertEqual(len(result), 5)

    def test_includes_titles_beyond_the_default_five(self):
        sre = Title.objects.create(tribe=self.tribe, name="Site Reliability Engineer", abbreviation="SRE")
        User.objects.create_user(username="sre1", role=User.Role.END_USER, title=sre, squad=self.squad)

        result = member_counts_by_title(self.squad.members.all(), self.tribe)
        by_code = {r["code"]: r for r in result}

        self.assertEqual(by_code[sre.pk]["total"], 1)
        self.assertEqual(by_code[sre.pk]["abbreviation"], "SRE")
        self.assertEqual(len(result), 6)

    def test_empty_members_gives_all_zero_counts(self):
        result = member_counts_by_title([], self.tribe)
        self.assertEqual(len(result), 5)
        self.assertTrue(all(r["total"] == 0 for r in result))

    def test_no_tribe_gives_empty_result(self):
        self.assertEqual(member_counts_by_title([], None), [])
