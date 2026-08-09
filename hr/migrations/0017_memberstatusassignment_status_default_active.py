from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0016_alter_dashboardsnooze_id"),
    ]

    operations = [
        migrations.AlterField(
            model_name="memberstatusassignment",
            name="status",
            field=models.CharField(
                choices=[("active", "Active"), ("away", "Away"), ("break", "Break")],
                default="active",
                max_length=20,
            ),
        ),
    ]
