from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import User
from apps.calendar_data.models import Sprint
from apps.org.models import Tribe
from apps.org.titles import seed_default_titles


def _first_monday_of(year):
    jan_first = date(year, 1, 1)
    return jan_first + timedelta(days=(7 - jan_first.weekday()) % 7)


class SprintAdminNoManualAddTests(TestCase):
    """Sprints must only ever be created a whole quarter at a time via
    "Generate sprints for a quarter" - adding one by hand would sidestep
    the contiguity, SP-numbering and Monday-to-Friday rules."""

    def setUp(self):
        self.tribe = Tribe.objects.create(name="Tribe A")
        self.titles = seed_default_titles(self.tribe)
        self.admin = User.objects.create_user(
            username="sm1", password="pass1234", title=self.titles["scrum_master"]
        )
        self.client.login(username="sm1", password="pass1234")

    def test_add_view_is_forbidden(self):
        response = self.client.get("/admin/calendar_data/sprint/add/")
        self.assertEqual(response.status_code, 403)

    def test_changelist_offers_generate_but_not_add(self):
        response = self.client.get("/admin/calendar_data/sprint/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Generate sprints for a quarter")
        self.assertNotContains(response, "/admin/calendar_data/sprint/add/")

    def test_generating_a_quarter_still_works(self):
        year = date.today().year
        monday = _first_monday_of(year)
        end = monday + timedelta(days=25)  # 4 weeks -> 2 sprints, ending on a Friday
        response = self.client.post(
            "/admin/calendar_data/sprint/generate/",
            {
                "tribe": self.tribe.pk,
                "year": year,
                "quarter": Sprint.Quarter.Q1,
                "start_date": monday.isoformat(),
                "end_date": end.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            list(Sprint.objects.order_by("name").values_list("name", flat=True)), ["SP1", "SP2"]
        )

    def test_year_dropdown_offers_current_next_previous_in_that_order(self):
        response = self.client.get("/admin/calendar_data/sprint/generate/")
        current = date.today().year
        self.assertEqual(
            list(response.context["form"].fields["year"].choices),
            [(current, str(current)), (current + 1, str(current + 1)), (current - 1, str(current - 1))],
        )
        # ...and the current year is the one pre-selected in the rendered form
        self.assertEqual(response.context["form"]["year"].value(), current)
        self.assertInHTML(
            f'<option value="{current}" selected>{current}</option>',
            response.content.decode(),
        )

    def test_year_outside_the_offered_range_is_rejected(self):
        year = date.today().year
        monday = _first_monday_of(year)
        response = self.client.post(
            "/admin/calendar_data/sprint/generate/",
            {
                "tribe": self.tribe.pk,
                "year": year + 5,
                "quarter": Sprint.Quarter.Q1,
                "start_date": monday.isoformat(),
                "end_date": (monday + timedelta(days=25)).isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)  # redisplayed with an error
        self.assertFalse(Sprint.objects.exists())

    def test_existing_sprints_remain_editable_and_deletable(self):
        sprint = Sprint.objects.create(
            tribe=self.tribe,
            year=2026,
            quarter=Sprint.Quarter.Q1,
            name="SP1",
            start_date=date(2026, 1, 5),
            end_date=date(2026, 1, 16),
        )
        response = self.client.get(f"/admin/calendar_data/sprint/{sprint.pk}/change/")
        self.assertEqual(response.status_code, 200)
        response = self.client.get(f"/admin/calendar_data/sprint/{sprint.pk}/delete/")
        self.assertEqual(response.status_code, 200)
