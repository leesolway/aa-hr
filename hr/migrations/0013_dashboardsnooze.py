from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0012_remove_memberstatus"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DashboardSnooze",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("snoozed_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField(blank=True, help_text="Auto-clears after this date. Leave blank for indefinite.", null=True)),
                ("note", models.TextField(help_text="Reason for snoozing this member's warnings.")),
                ("snoozed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="hr_dashboard_snooze", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "Dashboard — Snooze",
                "verbose_name_plural": "Dashboard — Snoozes",
            },
        ),
    ]
