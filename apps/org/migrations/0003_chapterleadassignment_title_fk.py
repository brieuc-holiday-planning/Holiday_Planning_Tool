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


def migrate_assignment_titles(apps, schema_editor):
    Title = apps.get_model("org", "Title")
    ChapterLeadAssignment = apps.get_model("org", "ChapterLeadAssignment")

    titles_by_tribe = {}
    for assignment in ChapterLeadAssignment.objects.select_related("tribe").all():
        titles = titles_by_tribe.setdefault(
            assignment.tribe_id, _get_or_seed_titles(Title, assignment.tribe)
        )
        title = titles.get(assignment.title_code)
        if title is None:
            title, _ = Title.objects.get_or_create(
                tribe=assignment.tribe,
                name=(assignment.title_code or "Unknown").replace("_", " ").title(),
                defaults={"abbreviation": (assignment.title_code or "unk")[:3].upper()},
            )
        assignment.title = title
        assignment.save(update_fields=["title"])


class Migration(migrations.Migration):

    dependencies = [
        ("org", "0002_title"),
    ]

    operations = [
        # Clear the old (tribe, title) unique_together before renaming the
        # field it references, so the migration state is never left
        # pointing at a stale field name.
        migrations.AlterUniqueTogether(name="chapterleadassignment", unique_together=set()),
        migrations.AlterModelOptions(name="chapterleadassignment", options={}),
        migrations.RenameField(model_name="chapterleadassignment", old_name="title", new_name="title_code"),
        migrations.AddField(
            model_name="chapterleadassignment",
            name="title",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="chapter_lead_assignments",
                to="org.title",
            ),
        ),
        migrations.RunPython(migrate_assignment_titles, reverse_code=migrations.RunPython.noop),
        migrations.RemoveField(model_name="chapterleadassignment", name="title_code"),
        migrations.AlterField(
            model_name="chapterleadassignment",
            name="title",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="chapter_lead_assignments",
                to="org.title",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="chapterleadassignment",
            unique_together={("tribe", "title")},
        ),
        migrations.AlterModelOptions(
            name="chapterleadassignment",
            options={"ordering": ["tribe__name", "title__name"]},
        ),
    ]
