from django.db import migrations


def seed_grants_admin_access(apps, schema_editor):
    """There's no separate "Scrum Master" role on User anymore - admin
    access is granted purely by title (see accounts.User.is_scrum_master),
    so every existing Title named "Scrum Master" (the one every tribe was
    seeded with) needs grants_admin_access=True to preserve current admin
    access for whoever already holds it."""
    Title = apps.get_model("org", "Title")
    Title.objects.filter(name="Scrum Master").update(grants_admin_access=True)


class Migration(migrations.Migration):

    dependencies = [
        ("org", "0006_title_grants_admin_access"),
    ]

    operations = [
        migrations.RunPython(seed_grants_admin_access, reverse_code=migrations.RunPython.noop),
    ]
