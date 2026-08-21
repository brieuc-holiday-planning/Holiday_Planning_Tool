from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Sprint

# A sprint is always Monday of week N to Friday of week N+1 - 10 working
# days (2 calendar weeks). 11 days after a Monday lands on the Friday of the
# following week.
SPRINT_SPAN_DAYS = 11
MAX_SPRINTS_PER_QUARTER = 8


def generate_sprints_for_quarter(tribe, year, quarter, start_date, end_date):
    """Validates the quarter's Monday-to-Friday date range and creates the
    SP1..SPN Sprint rows that tile it in consecutive 2-week blocks.

    Raises ValidationError (with all applicable messages) if the range is
    invalid, and never creates anything in that case.
    """
    errors = []

    if start_date.weekday() != 0:
        errors.append("The start date must be a Monday.")
    if end_date.weekday() != 4:
        errors.append("The end date must be a Friday.")
    if end_date <= start_date:
        errors.append("The end date must be after the start date.")

    if errors:
        raise ValidationError(errors)

    weeks = ((end_date - start_date).days // 7) + 1
    if weeks % 2 != 0:
        raise ValidationError(
            f"The range spans {weeks} week(s), which is not a multiple of 2 - "
            "it can't be tiled into whole 2-week sprints. Adjust the start or end date."
        )

    sprint_count = weeks // 2
    if sprint_count > MAX_SPRINTS_PER_QUARTER:
        raise ValidationError(
            f"This range would generate {sprint_count} sprints; a quarter can have at most "
            f"{MAX_SPRINTS_PER_QUARTER}."
        )

    if Sprint.objects.filter(tribe=tribe, year=year, quarter=quarter).exists():
        raise ValidationError(
            f"Sprints already exist for {Sprint.Quarter(quarter).label} {year}. "
            "Delete them first to regenerate."
        )

    # A week can only ever be covered by one sprint, so the requested range
    # must be clear of every existing sprint in the tribe - not just of the
    # quarter being generated. Overlaps typically mean a neighbouring
    # quarter's range was set a week or two too wide.
    overlapping = Sprint.overlapping(tribe, start_date, end_date)
    clash_count = overlapping.count()
    if clash_count:
        listed = "; ".join(str(sprint) for sprint in overlapping[:5])
        remainder = f" (and {clash_count - 5} more)" if clash_count > 5 else ""
        raise ValidationError(
            f"These dates overlap {clash_count} existing sprint(s): {listed}{remainder}. "
            "Delete them first, then generate this quarter again."
        )

    sprints = [
        Sprint(
            tribe=tribe,
            year=year,
            quarter=quarter,
            name=f"SP{i + 1}",
            start_date=start_date + timedelta(weeks=2 * i),
            end_date=start_date + timedelta(weeks=2 * i, days=SPRINT_SPAN_DAYS),
        )
        for i in range(sprint_count)
    ]

    with transaction.atomic():
        Sprint.objects.bulk_create(sprints)

    return sprints
