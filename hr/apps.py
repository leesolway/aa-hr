from django.apps import AppConfig


class HrConfig(AppConfig):
    name = "hr"
    verbose_name = "HR"

    def ready(self):
        from . import auth_hooks  # noqa: F401
        from . import signals  # noqa: F401
