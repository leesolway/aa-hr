from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0007_memberlabel_member_assignable_member_access_perm"),
    ]

    operations = [
        migrations.AddField(
            model_name="memberstatus",
            name="member_assignable",
            field=models.BooleanField(
                default=False,
                help_text="Allow members to set and clear this status themselves via the member dashboard.",
            ),
        ),
    ]
