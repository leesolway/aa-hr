from django.apps import AppConfig


class HrConfig(AppConfig):
    name = "hr"
    verbose_name = "HR"

    def ready(self):
        from . import auth_hooks  # noqa: F401
        from . import signals  # noqa: F401

        from celery import current_app
        from celery.schedules import crontab

        current_app.conf.beat_schedule.setdefault(
            "hr-check-member-inactivity",
            {
                "task": "hr.tasks.check_member_inactivity",
                "schedule": crontab(hour=3, minute=0),  # daily at 03:00
            },
        )
