from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("authentication", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Add aa_state to HrConfiguration
        migrations.AddField(
            model_name="hrconfiguration",
            name="aa_state",
            field=models.ForeignKey(
                blank=True,
                help_text="Only members in this state are shown in the HR module.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="authentication.state",
            ),
        ),
        # Update permissions on HrConfiguration
        migrations.AlterModelOptions(
            name="hrconfiguration",
            options={
                "permissions": [
                    ("access_hr", "Can access the HR module"),
                    ("manage_ranks", "Can create and edit rank definitions"),
                    ("manage_hr_roles", "Can assign HR roles to users"),
                ]
            },
        ),
        # Create Rank
        migrations.CreateModel(
            name="Rank",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("priority", models.PositiveIntegerField(default=0, help_text="Lower = more junior")),
                ("eve_title", models.CharField(
                    blank=True, default="", max_length=500,
                    help_text="Exact EVE title string to match against corptools character titles.",
                )),
                ("description", models.TextField(blank=True, default="")),
                ("is_active", models.BooleanField(default=True)),
                ("auth_group", models.OneToOneField(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="hr_rank",
                    to="auth.group",
                )),
            ],
            options={"ordering": ["priority"]},
        ),
        # Create HrRole
        migrations.CreateModel(
            name="HrRole",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("description", models.TextField(blank=True, default="")),
                ("can_assign", models.ManyToManyField(
                    blank=True, related_name="assignable_by_roles", to="hr.rank",
                )),
                ("can_remove", models.ManyToManyField(
                    blank=True, related_name="removable_by_roles", to="hr.rank",
                )),
            ],
            options={"ordering": ["name"]},
        ),
        # Create RankAssignment
        migrations.CreateModel(
            name="RankAssignment",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("assigned_at", models.DateTimeField(auto_now_add=True)),
                ("notes", models.TextField(blank=True, default="")),
                ("is_current", models.BooleanField(default=True)),
                ("assigned_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="hr_ranks_assigned",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("rank", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="assignments",
                    to="hr.rank",
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="hr_rank_assignments",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ["-assigned_at"]},
        ),
        migrations.AddIndex(
            model_name="rankassignment",
            index=models.Index(
                fields=["user", "is_current"],
                name="hr_rankassignment_user_cur_idx",
            ),
        ),
        # Create HrRoleAssignment
        migrations.CreateModel(
            name="HrRoleAssignment",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("assigned_at", models.DateTimeField(auto_now_add=True)),
                ("assigned_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="hr_roles_assigned",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("hr_role", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="assignments",
                    to="hr.hrrole",
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="hr_role_assignments",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.AlterUniqueTogether(
            name="hrroleassignment",
            unique_together={("user", "hr_role")},
        ),
        # Create RankAuditLog
        migrations.CreateModel(
            name="RankAuditLog",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("timestamp", models.DateTimeField(auto_now_add=True)),
                ("action", models.CharField(
                    choices=[
                        ("assigned", "Assigned"),
                        ("removed", "Removed"),
                        ("changed", "Changed"),
                    ],
                    max_length=20,
                )),
                ("notes", models.TextField(blank=True, default="")),
                ("new_rank", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+",
                    to="hr.rank",
                )),
                ("old_rank", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+",
                    to="hr.rank",
                )),
                ("performed_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="hr_audit_actions",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="hr_audit_log_entries",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ["-timestamp"]},
        ),
        migrations.AddIndex(
            model_name="rankauditlog",
            index=models.Index(
                fields=["user", "-timestamp"],
                name="hr_auditlog_user_ts_idx",
            ),
        ),
    ]
