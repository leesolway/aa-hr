from django.db import migrations, models


def set_inactive_label(apps, schema_editor):
    """Update the singleton's label from 'Break' to 'Inactive' if unchanged."""
    HrConfiguration = apps.get_model("hr", "HrConfiguration")
    HrConfiguration.objects.filter(inactive_label="Break").update(inactive_label="Inactive")


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0022_hrconfiguration_inactivity_threshold"),
    ]

    operations = [
        migrations.RenameField(
            model_name="hrconfiguration",
            old_name="break_auth_group",
            new_name="inactive_auth_group",
        ),
        migrations.RenameField(
            model_name="hrconfiguration",
            old_name="break_label",
            new_name="inactive_label",
        ),
        migrations.AlterField(
            model_name="hrconfiguration",
            name="inactive_label",
            field=models.CharField(
                default="Inactive",
                max_length=50,
                help_text="Display name for the Inactive status.",
            ),
        ),
        migrations.RunPython(set_inactive_label, migrations.RunPython.noop),
    ]
