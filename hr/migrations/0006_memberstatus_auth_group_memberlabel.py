# Generated migration

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("hr", "0005_member_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="memberstatus",
            name="auth_group",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="hr_member_status",
                to="auth.group",
                help_text="AA group to add the member to when this status is applied.",
            ),
        ),
        migrations.CreateModel(
            name="LabelCategory",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
                ("description", models.TextField(blank=True, default="")),
                ("display_order", models.PositiveIntegerField(default=0)),
            ],
            options={
                "verbose_name": "Label Category",
                "verbose_name_plural": "Label Categories",
                "ordering": ["display_order", "name"],
            },
        ),
        migrations.CreateModel(
            name="MemberLabel",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
                ("description", models.TextField(blank=True, default="")),
                ("is_active", models.BooleanField(default=True)),
                (
                    "category",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="labels",
                        to="hr.labelcategory",
                        help_text="Groups this label with others of the same type in the UI.",
                    ),
                ),
                (
                    "auth_group",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="hr_member_label",
                        to="auth.group",
                        help_text="AA group linked to this label. Members are added/removed automatically.",
                    ),
                ),
            ],
            options={
                "verbose_name": "Member Label",
                "verbose_name_plural": "Member Labels",
                "ordering": ["category__display_order", "category__name", "name"],
            },
        ),
        migrations.CreateModel(
            name="MemberLabelAssignment",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("assigned_at", models.DateTimeField(auto_now_add=True)),
                ("notes", models.TextField(blank=True, default="")),
                (
                    "assigned_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="hr_labels_assigned",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "label",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assignments",
                        to="hr.memberlabel",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="hr_label_assignments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["label__name"],
            },
        ),
        migrations.AlterUniqueTogether(
            name="memberlabelassignment",
            unique_together={("user", "label")},
        ),
        migrations.CreateModel(
            name="MemberLabelLog",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(choices=[("assigned", "Assigned"), ("removed", "Removed")], max_length=10)),
                ("timestamp", models.DateTimeField(auto_now_add=True)),
                ("notes", models.TextField(blank=True, default="")),
                (
                    "label",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="hr.memberlabel",
                    ),
                ),
                (
                    "performed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="hr_label_log_actions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="hr_label_log",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-timestamp"],
                "indexes": [
                    models.Index(fields=["user", "-timestamp"], name="hr_labellog_user_ts_idx"),
                ],
            },
        ),
    ]
