import django.db.models.deletion
from django.db import migrations, models

DEFAULT_TITLES = [
    ("scrum_master", "Scrum Master", "SM"),
    ("product_owner", "Product Owner", "PO"),
    ("data_scientist", "Data Scientist", "DS"),
    ("ai_engineer", "AI Engineer", "AI"),
    ("business_analyst", "Business Analyst", "BA"),
]


def _get_or_seed_titles(Title, tribe):
    titles = {}
    for code, name, abbreviation in DEFAULT_TITLES:
        title, _ = Title.objects.get_or_create(tribe=tribe, name=name, defaults={"abbreviation": abbreviation})
        titles[code] = title
    return titles


def migrate_user_titles(apps, schema_editor):
    Tribe = apps.get_model("org", "Tribe")
    Title = apps.get_model("org", "Title")
    User = apps.get_model("accounts", "User")

    titles_by_tribe = {tribe.pk: _get_or_seed_titles(Title, tribe) for tribe in Tribe.objects.all()}
    fallback_tribe_id = Tribe.objects.values_list("pk", flat=True).first()

    for user in User.objects.all():
        tribe_id = user.squad.cluster.tribe_id if user.squad_id else fallback_tribe_id
        if tribe_id is None:
            continue  # no tribe exists yet at all - nothing sensible to link to

        titles = titles_by_tribe.setdefault(tribe_id, _get_or_seed_titles(Title, Tribe.objects.get(pk=tribe_id)))
        title = titles.get(user.title_code)
        if title is None:
            # Unknown legacy value - preserve it verbatim rather than
            # silently dropping the user's profile information.
            tribe = Tribe.objects.get(pk=tribe_id)
            title, _ = Title.objects.get_or_create(
                tribe=tribe,
                name=(user.title_code or "Unknown").replace("_", " ").title(),
                defaults={"abbreviation": (user.title_code or "unk")[:3].upper()},
            )
        user.title = title
        user.save(update_fields=["title"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_initial"),
        ("org", "0002_title"),
    ]

    operations = [
        migrations.RenameField(model_name="user", old_name="title", new_name="title_code"),
        migrations.AddField(
            model_name="user",
            name="title",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="users",
                to="org.title",
            ),
        ),
        migrations.RunPython(migrate_user_titles, reverse_code=migrations.RunPython.noop),
        migrations.RemoveField(model_name="user", name="title_code"),
        migrations.AlterField(
            model_name="user",
            name="title",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="users",
                to="org.title",
            ),
        ),
    ]
