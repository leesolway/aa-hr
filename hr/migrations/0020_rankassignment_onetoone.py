from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def delete_stale_rank_assignments(apps, schema_editor):
    """Remove all non-current RankAssignment rows before the unique constraint is applied."""
    RankAssignment = apps.get_model("hr", "RankAssignment")
    RankAssignment.objects.filter(is_current=False).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0019_group_sync_action"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Purge history rows first so the unique constraint can be applied cleanly
        migrations.RunPython(
            delete_stale_rank_assignments,
            reverse_code=migrations.RunPython.noop,
        ),
        # Drop the compound index before removing the field it references
        migrations.RemoveIndex(
            model_name="rankassignment",
            name="hr_rankassignment_user_cur_idx",
        ),
        migrations.RemoveField(
            model_name="rankassignment",
            name="is_current",
        ),
        # Promote user FK to OneToOneField (adds UNIQUE constraint at DB level)
        migrations.AlterField(
            model_name="rankassignment",
            name="user",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="hr_rank_assignment",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
