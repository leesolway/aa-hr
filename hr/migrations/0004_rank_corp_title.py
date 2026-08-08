import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("corptools", "0126_assetsfilter_reversed_logic"),
        ("hr", "0003_rename_hrrole_role_rename_hrroleassignment_roleassignment"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="rank",
            name="eve_title",
        ),
        migrations.AddField(
            model_name="rank",
            name="corp_title",
            field=models.ForeignKey(
                blank=True,
                help_text="EVE title that members at this rank should have on all characters.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="hr_ranks",
                to="corptools.charactertitle",
            ),
        ),
    ]
