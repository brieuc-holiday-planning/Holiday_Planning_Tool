from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.calendar_data import services
from apps.calendar_data.models import Sprint
from apps.org.models import Tribe


def _next_monday(base):
    days_ahead = (0 - base.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return base + timedelta(days=days_ahead)


def _end_for_n_sprints(start, n):
    """A Monday `start` plus n consecutive 2-week sprints lands on the
    Friday of the n-th 2-week block: n * 14 days minus a weekend (3 days)."""
    return start + timedelta(days=14 * n - 3)


class GenerateSprintsForQuarterTests(TestCase):
    def setUp(self):
        self.tribe = Tribe.objects.create(name="Tribe A")
        self.monday = _next_monday(date.today())

    def test_generates_expected_number_and_names(self):
        end = _end_for_n_sprints(self.monday, 6)
        sprints = services.generate_sprints_for_quarter(
            self.tribe, 2026, Sprint.Quarter.Q1, self.monday, end
        )
        self.assertEqual(len(sprints), 6)
        self.assertEqual([s.name for s in sprints], [f"SP{i}" for i in range(1, 7)])
        self.assertEqual(sprints[0].start_date, self.monday)
        self.assertEqual(sprints[-1].end_date, end)
        for s in sprints:
            self.assertEqual(s.start_date.weekday(), 0)
            self.assertEqual(s.end_date.weekday(), 4)

    def test_consecutive_sprints_are_contiguous_2_week_blocks(self):
        end = _end_for_n_sprints(self.monday, 3)
        sprints = services.generate_sprints_for_quarter(
            self.tribe, 2026, Sprint.Quarter.Q1, self.monday, end
        )
        for prev, nxt in zip(sprints, sprints[1:]):
            self.assertEqual(nxt.start_date, prev.start_date + timedelta(weeks=2))
            self.assertEqual((prev.end_date - prev.start_date).days, 11)

    def test_start_date_not_monday_rejected(self):
        tuesday = self.monday + timedelta(days=1)
        end = _end_for_n_sprints(self.monday, 6)
        with self.assertRaises(ValidationError):
            services.generate_sprints_for_quarter(self.tribe, 2026, Sprint.Quarter.Q1, tuesday, end)

    def test_end_date_not_friday_rejected(self):
        end = _end_for_n_sprints(self.monday, 6) - timedelta(days=1)  # Thursday
        with self.assertRaises(ValidationError):
            services.generate_sprints_for_quarter(self.tribe, 2026, Sprint.Quarter.Q1, self.monday, end)

    def test_odd_number_of_weeks_rejected(self):
        valid_end = _end_for_n_sprints(self.monday, 6)  # 12 weeks, valid
        odd_end = valid_end + timedelta(days=7)  # 13 weeks, still a Friday
        with self.assertRaises(ValidationError):
            services.generate_sprints_for_quarter(
                self.tribe, 2026, Sprint.Quarter.Q1, self.monday, odd_end
            )

    def test_exactly_max_sprints_allowed(self):
        end = _end_for_n_sprints(self.monday, 8)
        sprints = services.generate_sprints_for_quarter(
            self.tribe, 2026, Sprint.Quarter.Q1, self.monday, end
        )
        self.assertEqual(len(sprints), 8)

    def test_more_than_max_sprints_rejected(self):
        end = _end_for_n_sprints(self.monday, 9)
        with self.assertRaises(ValidationError):
            services.generate_sprints_for_quarter(self.tribe, 2026, Sprint.Quarter.Q1, self.monday, end)

    def test_regenerating_same_quarter_rejected(self):
        end = _end_for_n_sprints(self.monday, 6)
        services.generate_sprints_for_quarter(self.tribe, 2026, Sprint.Quarter.Q1, self.monday, end)
        with self.assertRaises(ValidationError):
            services.generate_sprints_for_quarter(
                self.tribe, 2026, Sprint.Quarter.Q1, self.monday, end
            )

    def test_different_quarter_can_have_different_sprint_count(self):
        q1_end = _end_for_n_sprints(self.monday, 6)
        q1_sprints = services.generate_sprints_for_quarter(
            self.tribe, 2026, Sprint.Quarter.Q1, self.monday, q1_end
        )
        q2_start = q1_end + timedelta(days=3)  # next Monday after Q1's Friday
        q2_end = _end_for_n_sprints(q2_start, 7)
        q2_sprints = services.generate_sprints_for_quarter(
            self.tribe, 2026, Sprint.Quarter.Q2, q2_start, q2_end
        )
        self.assertEqual(len(q1_sprints), 6)
        self.assertEqual(len(q2_sprints), 7)
        # SP1 exists once per quarter, not globally unique - both batches
        # start their own numbering.
        self.assertEqual(q1_sprints[0].name, "SP1")
        self.assertEqual(q2_sprints[0].name, "SP1")

    def test_nothing_created_on_validation_failure(self):
        end = _end_for_n_sprints(self.monday, 6) + timedelta(days=7)  # odd weeks
        with self.assertRaises(ValidationError):
            services.generate_sprints_for_quarter(self.tribe, 2026, Sprint.Quarter.Q1, self.monday, end)
        self.assertEqual(Sprint.objects.count(), 0)


class SprintOverlapTests(TestCase):
    """A week can only ever be covered by one sprint: a new quarter's range
    must be clear of every existing sprint in the tribe, not just of the
    quarter being generated."""

    def setUp(self):
        self.tribe = Tribe.objects.create(name="Tribe A")
        self.monday = _next_monday(date.today())
        self.q1_end = _end_for_n_sprints(self.monday, 4)
        services.generate_sprints_for_quarter(
            self.tribe, 2026, Sprint.Quarter.Q1, self.monday, self.q1_end
        )

    def _generate_q2(self, start, sprints=2):
        return services.generate_sprints_for_quarter(
            self.tribe, 2026, Sprint.Quarter.Q2, start, _end_for_n_sprints(start, sprints)
        )

    def test_quarter_starting_inside_an_existing_sprint_rejected(self):
        overlapping_start = self.monday + timedelta(weeks=2)  # inside Q1's SP2
        with self.assertRaises(ValidationError) as ctx:
            self._generate_q2(overlapping_start)
        self.assertIn("overlap", " ".join(ctx.exception.messages).lower())
        self.assertEqual(Sprint.objects.filter(quarter=Sprint.Quarter.Q2).count(), 0)

    def test_quarter_overlapping_by_a_single_week_rejected(self):
        # starts one week before Q1 ends, so its first sprint straddles the seam
        overlapping_start = self.q1_end - timedelta(days=4)
        with self.assertRaises(ValidationError):
            self._generate_q2(overlapping_start)
        self.assertEqual(Sprint.objects.filter(quarter=Sprint.Quarter.Q2).count(), 0)

    def test_quarter_starting_the_monday_after_is_allowed(self):
        sprints = self._generate_q2(self.q1_end + timedelta(days=3))
        self.assertEqual(len(sprints), 2)

    def test_error_names_the_sprints_to_delete(self):
        with self.assertRaises(ValidationError) as ctx:
            self._generate_q2(self.monday + timedelta(weeks=2))
        message = " ".join(ctx.exception.messages)
        self.assertIn("SP2", message)
        self.assertIn("Delete them first", message)

    def test_other_tribes_are_unaffected(self):
        other = Tribe.objects.create(name="Tribe B")
        sprints = services.generate_sprints_for_quarter(
            other, 2026, Sprint.Quarter.Q1, self.monday, self.q1_end
        )
        self.assertEqual(len(sprints), 4)

    def test_editing_a_sprint_onto_another_is_rejected(self):
        sp1, sp2 = Sprint.objects.order_by("start_date")[:2]
        sp1.end_date = sp2.end_date  # stretch SP1 across SP2
        with self.assertRaises(ValidationError):
            sp1.full_clean()

    def test_saving_a_sprint_unchanged_is_fine(self):
        Sprint.objects.order_by("start_date").first().full_clean()  # must not raise
