import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("org", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Title",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=50)),
                ("abbreviation", models.CharField(max_length=10)),
                (
                    "tribe",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="titles", to="org.tribe"
                    ),
                ),
            ],
            options={
                "ordering": ["tribe__name", "name"],
                "unique_together": {("tribe", "name"), ("tribe", "abbreviation")},
            },
        ),
    ]
