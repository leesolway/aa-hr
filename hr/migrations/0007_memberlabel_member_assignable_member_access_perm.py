# Generated migration

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0006_memberstatus_auth_group_memberlabel"),
    ]

    operations = [
        migrations.AddField(
            model_name="memberlabel",
            name="member_assignable",
            field=models.BooleanField(
                default=False,
                help_text="Allow members to assign and remove this label themselves via the member dashboard.",
            ),
        ),
        migrations.AlterModelOptions(
            name="hrconfiguration",
            options={
                "verbose_name": "Configuration",
                "verbose_name_plural": "Configuration",
                "permissions": [
                    ("access_hr", "Can access the HR module"),
                    ("member_access", "Can access the member self-service dashboard"),
                    ("manage_ranks", "Can create and edit rank definitions"),
                    ("manage_roles", "Can assign roles to users"),
                ],
            },
        ),
    ]
