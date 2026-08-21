"""Default Title rows seeded for every tribe. Scrum Masters can add more
and edit these freely afterward through the admin - this list only matters
at tribe-bootstrap time and for migrating pre-existing data."""

DEFAULT_TITLES = [
    ("scrum_master", "Scrum Master", "SM"),
    ("product_owner", "Product Owner", "PO"),
    ("data_scientist", "Data Scientist", "DS"),
    ("ai_engineer", "AI Engineer", "AI"),
    ("business_analyst", "Business Analyst", "BA"),
]


def seed_default_titles(tribe):
    """Idempotently creates the default titles for `tribe`. Returns
    {legacy_code: Title} for convenience (tests, bootstrap_tribe). The
    "Scrum Master" title is the only one seeded with grants_admin_access -
    that's what makes holders of it admins of the app (see
    accounts.User.is_scrum_master)."""
    from .models import Title

    titles = {}
    for code, name, abbreviation in DEFAULT_TITLES:
        title, _ = Title.objects.get_or_create(
            tribe=tribe,
            name=name,
            defaults={"abbreviation": abbreviation, "grants_admin_access": code == "scrum_master"},
        )
        titles[code] = title
    return titles
