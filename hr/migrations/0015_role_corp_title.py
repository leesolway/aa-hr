from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("corptools", "__first__"),
        ("hr", "0014_role_auth_group_auditlog_role_drop_memberlabellog"),
    ]

    operations = [
        migrations.AddField(
            model_name="role",
            name="corp_title",
            field=models.ForeignKey(
                blank=True,
                help_text="EVE title that members holding this role should have on all characters.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="hr_roles",
                to="corptools.charactertitle",
            ),
        ),
    ]
