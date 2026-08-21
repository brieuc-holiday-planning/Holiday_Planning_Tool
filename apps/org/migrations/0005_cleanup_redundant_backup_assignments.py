from django.db import migrations


def remove_self_referential_backups(apps, schema_editor):
    """ChapterLeadAssignment used to be how the *primary* Chapter Lead for a
    title was set. That's now derived directly from User.role/title instead
    (see accounts.User.one_chapter_lead_per_title), so any existing
    assignment row that just duplicates the person who's already the
    primary for that title is stale noise, not a real backup."""
    ChapterLeadAssignment = apps.get_model("org", "ChapterLeadAssignment")
    User = apps.get_model("accounts", "User")

    for assignment in ChapterLeadAssignment.objects.all():
        is_already_primary = User.objects.filter(
            pk=assignment.chapter_lead_id, role="chapter_lead", title_id=assignment.title_id
        ).exists()
        if is_already_primary:
            assignment.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("org", "0004_alter_chapterleadassignment_options_and_more"),
        ("accounts", "0004_remove_user_squad_required_unless_scrum_master_and_more"),
    ]

    operations = [
        migrations.RunPython(remove_self_referential_backups, reverse_code=migrations.RunPython.noop),
    ]
