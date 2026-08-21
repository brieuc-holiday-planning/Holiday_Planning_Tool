from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.calendar_data.models import BankHoliday, Event, Sprint
from apps.org.models import Cluster, Squad, Tribe


class SprintTests(TestCase):
    def setUp(self):
        self.tribe = Tribe.objects.create(name="Tribe A")

    def test_end_before_start_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Sprint.objects.create(
                tribe=self.tribe,
                year=2026,
                quarter=Sprint.Quarter.Q1,
                name="SP1",
                start_date=date(2026, 1, 15),
                end_date=date(2026, 1, 1),
            )

    def test_duplicate_name_within_same_tribe_year_quarter_rejected(self):
        Sprint.objects.create(
            tribe=self.tribe,
            year=2026,
            quarter=Sprint.Quarter.Q1,
            name="SP1",
            start_date=date(2026, 1, 5),
            end_date=date(2026, 1, 16),
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Sprint.objects.create(
                tribe=self.tribe,
                year=2026,
                quarter=Sprint.Quarter.Q1,
                name="SP1",
                start_date=date(2026, 2, 2),
                end_date=date(2026, 2, 13),
            )

    def test_same_name_allowed_in_different_quarter(self):
        Sprint.objects.create(
            tribe=self.tribe,
            year=2026,
            quarter=Sprint.Quarter.Q1,
            name="SP1",
            start_date=date(2026, 1, 5),
            end_date=date(2026, 1, 16),
        )
        Sprint.objects.create(
            tribe=self.tribe,
            year=2026,
            quarter=Sprint.Quarter.Q2,
            name="SP1",
            start_date=date(2026, 4, 6),
            end_date=date(2026, 4, 17),
        )  # should not raise


class BankHolidayTests(TestCase):
    def test_duplicate_date_within_tribe_rejected(self):
        tribe = Tribe.objects.create(name="Tribe A")
        BankHoliday.objects.create(tribe=tribe, date=date(2026, 12, 25), name="Christmas")
        with self.assertRaises(IntegrityError), transaction.atomic():
            BankHoliday.objects.create(tribe=tribe, date=date(2026, 12, 25), name="Christmas (dup)")


class EventScopeTests(TestCase):
    def setUp(self):
        self.tribe = Tribe.objects.create(name="Tribe A")
        self.cluster = Cluster.objects.create(tribe=self.tribe, name="Cluster A")
        self.squad = Squad.objects.create(cluster=self.cluster, name="Squad A")

    def test_tribe_scope_with_cluster_set_rejected_by_clean(self):
        event = Event(
            tribe=self.tribe,
            scope=Event.Scope.TRIBE,
            cluster=self.cluster,
            name="Bad",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 1),
        )
        with self.assertRaises(ValidationError):
            event.clean()

    def test_squad_scope_without_squad_rejected_by_db_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Event.objects.create(
                tribe=self.tribe,
                scope=Event.Scope.SQUAD,
                name="Bad",
                start_date=date(2026, 3, 1),
                end_date=date(2026, 3, 1),
            )

    def test_valid_squad_scoped_event_created(self):
        event = Event.objects.create(
            tribe=self.tribe,
            scope=Event.Scope.SQUAD,
            squad=self.squad,
            name="Offsite",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 2),
        )
        self.assertEqual(event.squad, self.squad)

    def test_end_before_start_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Event.objects.create(
                tribe=self.tribe,
                scope=Event.Scope.TRIBE,
                name="Bad dates",
                start_date=date(2026, 3, 10),
                end_date=date(2026, 3, 1),
            )
