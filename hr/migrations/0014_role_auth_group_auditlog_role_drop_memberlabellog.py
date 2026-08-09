from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("hr", "0013_dashboardsnooze"),
    ]

    operations = [
        migrations.AddField(
            model_name="role",
            name="auth_group",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="hr_role",
                to="auth.group",
            ),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="role",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="hr.role",
            ),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="action",
            field=models.CharField(
                max_length=20,
                choices=[
                    ("rank_assigned",  "Rank assigned"),
                    ("rank_changed",   "Rank changed"),
                    ("rank_removed",   "Rank removed"),
                    ("status_set",     "Status set"),
                    ("status_cleared", "Status cleared"),
                    ("label_assigned", "Label assigned"),
                    ("label_removed",  "Label removed"),
                    ("role_assigned",  "Role assigned"),
                    ("role_removed",   "Role removed"),
                ],
            ),
        ),
        migrations.DeleteModel(
            name="MemberLabelLog",
        ),
    ]
