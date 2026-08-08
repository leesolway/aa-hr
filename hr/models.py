from allianceauth.authentication.models import State
from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models
from solo.models import SingletonModel


class HrConfiguration(SingletonModel):
    aa_state = models.ForeignKey(
        State,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Only members in this state are shown in the HR module.",
    )

    class Meta:
        permissions = [
            ("access_hr", "Can access the HR module"),
            ("manage_ranks", "Can create and edit rank definitions"),
            ("manage_roles", "Can assign roles to users"),
        ]

    def __str__(self):
        return "HR Configuration"


class Rank(models.Model):
    name = models.CharField(max_length=100)
    priority = models.PositiveIntegerField(default=0)
    auth_group = models.OneToOneField(
        Group,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hr_rank",
    )
    corp_title = models.ForeignKey(
        "corptools.CharacterTitle",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hr_ranks",
        help_text="EVE title that members at this rank should have on all characters.",
    )
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["priority"]

    def __str__(self):
        return self.name


class RankAssignment(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="hr_rank_assignments",
    )
    rank = models.ForeignKey(Rank, on_delete=models.PROTECT, related_name="assignments")
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hr_ranks_assigned",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, default="")
    is_current = models.BooleanField(default=True)

    class Meta:
        ordering = ["-assigned_at"]
        indexes = [
            models.Index(
                fields=["user", "is_current"],
                name="hr_rankassignment_user_cur_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user} — {self.rank}"


class Role(models.Model):
    name = models.CharField(max_length=100)
    can_assign = models.ManyToManyField(
        Rank, blank=True, related_name="assignable_by_roles"
    )
    can_remove = models.ManyToManyField(
        Rank, blank=True, related_name="removable_by_roles"
    )
    description = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class RoleAssignment(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="role_assignments",
    )
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="assignments")
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="roles_assigned",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "role")]

    def __str__(self):
        return f"{self.user} — {self.role}"


class RankAuditLog(models.Model):
    ACTION_ASSIGNED = "assigned"
    ACTION_REMOVED = "removed"
    ACTION_CHANGED = "changed"
    ACTION_CHOICES = [
        (ACTION_ASSIGNED, "Assigned"),
        (ACTION_REMOVED, "Removed"),
        (ACTION_CHANGED, "Changed"),
    ]

    timestamp = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="hr_audit_log_entries",
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hr_audit_actions",
    )
    old_rank = models.ForeignKey(
        Rank,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    new_rank = models.ForeignKey(
        Rank,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(
                fields=["user", "-timestamp"],
                name="hr_auditlog_user_ts_idx",
            ),
        ]

    def __str__(self):
        return f"{self.get_action_display()} {self.user} at {self.timestamp}"
