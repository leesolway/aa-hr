from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0002_rank_hrrole_hrconfiguration_aa_state_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Rename models (renames DB tables)
        migrations.RenameModel("HrRole", "Role"),
        migrations.RenameModel("HrRoleAssignment", "RoleAssignment"),

        # Rename the FK field hr_role -> role on RoleAssignment
        migrations.RenameField(
            model_name="roleassignment",
            old_name="hr_role",
            new_name="role",
        ),

        # Update unique_together to reference new field name
        migrations.AlterUniqueTogether(
            name="roleassignment",
            unique_together={("user", "role")},
        ),

        # Update related_names on RoleAssignment (no DB change, state only)
        migrations.AlterField(
            model_name="roleassignment",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="role_assignments",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="roleassignment",
            name="assigned_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="roles_assigned",
                to=settings.AUTH_USER_MODEL,
            ),
        ),

        # Update permission codename
        migrations.AlterModelOptions(
            name="hrconfiguration",
            options={
                "permissions": [
                    ("access_hr", "Can access the HR module"),
                    ("manage_ranks", "Can create and edit rank definitions"),
                    ("manage_roles", "Can assign roles to users"),
                ]
            },
        ),
    ]
