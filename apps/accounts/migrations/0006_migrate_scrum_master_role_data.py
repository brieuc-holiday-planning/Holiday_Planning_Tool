from django.db import migrations


def migrate_scrum_master_role(apps, schema_editor):
    """Role.SCRUM_MASTER no longer exists - it's replaced by title-driven
    admin access (see accounts.User.is_scrum_master / org.Title.
    grants_admin_access, seeded onto the "Scrum Master" title by
    org.0007_seed_scrum_master_admin_title, which this migration depends
    on). Convert any existing role='scrum_master' row to 'end_user' (their
    title is untouched, so anyone already on the "Scrum Master" title keeps
    admin access), then recompute is_staff for every user under the new
    rule so admin access is preserved/corrected in both directions -
    including for users who already held an admin-granting title under a
    non-scrum_master role (e.g. Chapter Lead), who are newly promoted."""
    User = apps.get_model("accounts", "User")
    Permission = apps.get_model("auth", "Permission")

    User.objects.filter(role="scrum_master").update(role="end_user")

    silently_permitted_ids = set()
    try:
        perm = Permission.objects.get(content_type__app_label="holidays", codename="edit_any_holiday_silently")
    except Permission.DoesNotExist:
        perm = None
    if perm is not None:
        silently_permitted_ids = set(perm.user_set.values_list("pk", flat=True))

    for user in User.objects.select_related("title"):
        correct_is_staff = (
            user.is_superuser
            or (user.title_id and user.title.grants_admin_access)
            or user.pk in silently_permitted_ids
        )
        if user.is_staff != correct_is_staff:
            user.is_staff = correct_is_staff
            user.save(update_fields=["is_staff"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_remove_user_squad_required_unless_scrum_master_or_chapter_lead_and_more"),
    ]

    operations = [
        migrations.RunPython(migrate_scrum_master_role, reverse_code=migrations.RunPython.noop),
    ]
