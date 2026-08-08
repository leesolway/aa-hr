from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def migrate_audit_data(apps, schema_editor):
    AuditLog = apps.get_model("hr", "AuditLog")
    RankAuditLog = apps.get_model("hr", "RankAuditLog")
    MemberStatusLog = apps.get_model("hr", "MemberStatusLog")
    MemberLabelLog = apps.get_model("hr", "MemberLabelLog")

    ACTION_MAP = {
        "assigned": "rank_assigned",
        "changed":  "rank_changed",
        "removed":  "rank_removed",
    }

    bulk = []

    for entry in RankAuditLog.objects.all():
        bulk.append(AuditLog(
            timestamp=entry.timestamp,
            action=ACTION_MAP.get(entry.action, "rank_assigned"),
            user_id=entry.user_id,
            performed_by_id=entry.performed_by_id,
            old_rank_id=entry.old_rank_id,
            new_rank_id=entry.new_rank_id,
            notes=entry.notes,
        ))

    for entry in MemberStatusLog.objects.all():
        action = "status_cleared" if entry.new_status_id is None else "status_set"
        bulk.append(AuditLog(
            timestamp=entry.timestamp,
            action=action,
            user_id=entry.user_id,
            performed_by_id=entry.set_by_id,
            old_status_id=entry.old_status_id,
            new_status_id=entry.new_status_id,
            notes=entry.notes,
        ))

    for entry in MemberLabelLog.objects.all():
        action = "label_assigned" if entry.action == "assigned" else "label_removed"
        bulk.append(AuditLog(
            timestamp=entry.timestamp,
            action=action,
            user_id=entry.user_id,
            performed_by_id=entry.performed_by_id,
            label_id=entry.label_id,
            notes=entry.notes,
        ))

    AuditLog.objects.bulk_create(bulk)


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0008_memberstatus_member_assignable"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("timestamp", models.DateTimeField(auto_now_add=True)),
                ("action", models.CharField(
                    max_length=20,
                    choices=[
                        ("rank_assigned",  "Rank assigned"),
                        ("rank_changed",   "Rank changed"),
                        ("rank_removed",   "Rank removed"),
                        ("status_set",     "Status set"),
                        ("status_cleared", "Status cleared"),
                        ("label_assigned", "Label assigned"),
                        ("label_removed",  "Label removed"),
                        ("roles_cleared",  "Roles cleared"),
                    ],
                )),
                ("notes", models.TextField(blank=True, default="")),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="hr_audit_log",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("performed_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("old_rank", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to="hr.rank",
                )),
                ("new_rank", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to="hr.rank",
                )),
                ("old_status", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to="hr.memberstatus",
                )),
                ("new_status", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to="hr.memberstatus",
                )),
                ("label", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to="hr.memberlabel",
                )),
            ],
            options={
                "verbose_name": "Audit Log Entry",
                "verbose_name_plural": "Audit Log",
                "ordering": ["-timestamp"],
            },
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(fields=["user", "-timestamp"], name="hr_audit_user_ts_idx"),
        ),
        migrations.RunPython(migrate_audit_data, migrations.RunPython.noop),
        migrations.DeleteModel("RankAuditLog"),
        migrations.DeleteModel("MemberStatusLog"),
        migrations.DeleteModel("MemberLabelLog"),
    ]
