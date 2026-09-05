from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0021_hrconfiguration_status_labels"),
    ]

    operations = [
        migrations.AddField(
            model_name="hrconfiguration",
            name="inactivity_threshold_days",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                help_text=(
                    "Automatically apply the Break status to members whose most recent EVE login "
                    "(across all characters) exceeds this many days. Leave blank to disable."
                ),
            ),
        ),
    ]
