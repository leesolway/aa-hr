from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0020_rankassignment_onetoone"),
    ]

    operations = [
        migrations.AddField(
            model_name="hrconfiguration",
            name="active_label",
            field=models.CharField(default="Active", max_length=50, help_text="Display name for the Active status."),
        ),
        migrations.AddField(
            model_name="hrconfiguration",
            name="away_label",
            field=models.CharField(default="Away", max_length=50, help_text="Display name for the Away status."),
        ),
        migrations.AddField(
            model_name="hrconfiguration",
            name="break_label",
            field=models.CharField(default="Break", max_length=50, help_text="Display name for the Break status."),
        ),
    ]
