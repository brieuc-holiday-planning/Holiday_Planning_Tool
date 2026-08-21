import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def migrate_status_to_days(apps, schema_editor):
    HolidayRequest = apps.get_model("holidays", "HolidayRequest")
    for request in HolidayRequest.objects.all():
        request.days.update(
            status=request.status,
            decided_at=request.decided_at,
            decided_by_id=request.decided_by_id,
            decision_reason=request.decision_reason,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("holidays", "0002_alter_holidayrequest_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="holidayrequestday",
            name="status",
            field=models.CharField(
                choices=[("pending", "Pending"), ("approved", "Approved"), ("refused", "Refused")],
                default="pending",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="holidayrequestday",
            name="decided_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="holidayrequestday",
            name="decided_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="holiday_day_decisions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="holidayrequestday",
            name="decision_reason",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.RunPython(migrate_status_to_days, reverse_code=migrations.RunPython.noop),
        migrations.RemoveField(model_name="holidayrequest", name="status"),
        migrations.RemoveField(model_name="holidayrequest", name="decided_at"),
        migrations.RemoveField(model_name="holidayrequest", name="decided_by"),
        migrations.RemoveField(model_name="holidayrequest", name="decision_reason"),
    ]
