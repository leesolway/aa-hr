from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def migrate_status_groups(apps, schema_editor):
    """Copy auth_group from MemberStatus records into HrConfiguration."""
    HrConfiguration = apps.get_model("hr", "HrConfiguration")
    MemberStatus = apps.get_model("hr", "MemberStatus")
    config = HrConfiguration.objects.first()
    if not config:
        return
    for status in MemberStatus.objects.select_related("auth_group"):
        if not status.auth_group_id:
            continue
        name = status.name.lower()
        if "break" in name:
            config.break_auth_group_id = status.auth_group_id
        elif "away" in name:
            config.away_auth_group_id = status.auth_group_id
    config.save(update_fields=["away_auth_group_id", "break_auth_group_id"])


def migrate_status_assignments(apps, schema_editor):
    """Populate the new status CharField from the old MemberStatus FK name."""
    MemberStatusAssignment = apps.get_model("hr", "MemberStatusAssignment")
    for assignment in MemberStatusAssignment.objects.select_related("status_fk"):
        if not assignment.status_fk:
            assignment.status = "away"
        else:
            name = assignment.status_fk.name.lower()
            assignment.status = "break" if "break" in name else "away"
        assignment.save(update_fields=["status"])


def migrate_audit_log_status(apps, schema_editor):
    """Populate new old_status/new_status CharFields from the old MemberStatus FKs."""
    AuditLog = apps.get_model("hr", "AuditLog")
    updates = []
    for entry in AuditLog.objects.filter(
        old_status_fk__isnull=False
    ).select_related("old_status_fk", "new_status_fk"):
        entry.old_status = entry.old_status_fk.name.lower() if entry.old_status_fk else ""
        entry.new_status = entry.new_status_fk.name.lower() if entry.new_status_fk else ""
        updates.append(entry)
    if updates:
        AuditLog.objects.bulk_update(updates, ["old_status", "new_status"])


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("hr", "0011_remove_memberstatuslog"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── HrConfiguration: add Away/Break group fields ─────────────────────
        migrations.AddField(
            model_name="hrconfiguration",
            name="away_auth_group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="auth.group",
                help_text="AA group assigned to members with Away status.",
            ),
        ),
        migrations.AddField(
            model_name="hrconfiguration",
            name="break_auth_group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="auth.group",
                help_text="AA group assigned to members on Break.",
            ),
        ),
        # Migrate auth_group from existing MemberStatus records into config
        migrations.RunPython(migrate_status_groups, migrations.RunPython.noop),

        # ── MemberStatusAssignment: FK → CharField ───────────────────────────
        migrations.RenameField(
            model_name="memberstatusassignment",
            old_name="status",
            new_name="status_fk",
        ),
        migrations.AddField(
            model_name="memberstatusassignment",
            name="status",
            field=models.CharField(
                max_length=20,
                choices=[("active", "Active"), ("away", "Away"), ("break", "Break")],
                default="away",
            ),
            preserve_default=False,
        ),
        migrations.RunPython(migrate_status_assignments, migrations.RunPython.noop),
        migrations.RemoveField(model_name="memberstatusassignment", name="status_fk"),

        # ── AuditLog: old_status/new_status FK → CharField ───────────────────
        migrations.RenameField(
            model_name="auditlog",
            old_name="old_status",
            new_name="old_status_fk",
        ),
        migrations.RenameField(
            model_name="auditlog",
            old_name="new_status",
            new_name="new_status_fk",
        ),
        migrations.AddField(
            model_name="auditlog",
            name="old_status",
            field=models.CharField(max_length=20, blank=True, default=""),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="new_status",
            field=models.CharField(max_length=20, blank=True, default=""),
        ),
        migrations.RunPython(migrate_audit_log_status, migrations.RunPython.noop),
        migrations.RemoveField(model_name="auditlog", name="old_status_fk"),
        migrations.RemoveField(model_name="auditlog", name="new_status_fk"),

        # ── Drop MemberStatus table ───────────────────────────────────────────
        migrations.DeleteModel(name="MemberStatus"),
    ]
