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
    home_corp = models.ForeignKey(
        "eveonline.EveCorporationInfo",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text=(
            "Restrict member list and title checks to this corporation. "
            "Leave blank to include all members in the configured state."
        ),
    )
    away_auth_group = models.ForeignKey(
        "auth.Group",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="AA group assigned to members with Away status.",
    )
    break_auth_group = models.ForeignKey(
        "auth.Group",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="AA group assigned to members on Break.",
    )

    class Meta:
        verbose_name = "Configuration"
        verbose_name_plural = "Configuration"
        permissions = [
            ("access_hr", "Can access the HR module"),
            ("member_access", "Can access the member self-service dashboard"),
            ("manage_ranks", "Can create and edit rank definitions"),
            ("manage_roles", "Can assign roles to users"),
        ]

    @property
    def home_corporation_id(self):
        """The corporation_id of home_corp, or None if not set."""
        return self.home_corp.corporation_id if self.home_corp_id else None

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
        verbose_name = "Rank — Definition"
        verbose_name_plural = "Rank — Definitions"

    def __str__(self):
        return self.name


class RankAssignment(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="hr_rank_assignment",
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

    class Meta:
        verbose_name = "Rank — Assignment"
        verbose_name_plural = "Rank — Assignments"

    def __str__(self):
        return f"{self.user} — {self.rank}"


class Role(models.Model):
    name = models.CharField(max_length=100)
    auth_group = models.OneToOneField(
        "auth.Group",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hr_role",
    )
    corp_title = models.ForeignKey(
        "corptools.CharacterTitle",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hr_roles",
        help_text="EVE title that members holding this role should have on their characters.",
    )
    title_main_only = models.BooleanField(
        default=False,
        help_text="Only require the main character to hold the in-game title, not all characters.",
    )
    can_assign = models.ManyToManyField(
        Rank, blank=True, related_name="assignable_by_roles"
    )
    can_remove = models.ManyToManyField(
        Rank, blank=True, related_name="removable_by_roles"
    )
    description = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["name"]
        verbose_name = "Role — Definition"
        verbose_name_plural = "Role — Definitions"

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
        verbose_name = "Role — Assignment"
        verbose_name_plural = "Role — Assignments"

    def __str__(self):
        return f"{self.user} — {self.role}"


class MemberStatusAssignment(models.Model):
    """Status record for a user.

    ACTIVE is the default and represents normal/active state. A row with
    status='active' and an absent row are treated identically — the member
    is considered active. Views map an 'active' submission to
    clear_member_status(), which deletes the row to normalise state, but if
    an 'active' row persists (e.g. created via admin) all service and
    display logic handles it correctly. AWAY and BREAK add the member to a
    status group and suppress dashboard title-mismatch alerts. BREAK
    additionally removes rank and all role assignments.
    """

    ACTIVE = "active"
    AWAY = "away"
    BREAK = "break"
    STATUS_CHOICES = [
        (ACTIVE, "Active"),
        (AWAY, "Away"),
        (BREAK, "Break"),
    ]

    # Behaviour constants — no DB flags needed
    REMOVES_RANK = frozenset({BREAK})

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="hr_member_status",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=ACTIVE)
    set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hr_statuses_set",
    )
    set_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Status — Assignment"
        verbose_name_plural = "Status — Assignments"

    def __str__(self):
        return f"{self.user} — {self.get_status_display()}"


class LabelCategory(models.Model):
    """Groups related MemberLabels together for display in the UI.

    Examples: 'Timezone', 'Activity', 'Special'.
    """

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "name"]
        verbose_name = "Label — Category"
        verbose_name_plural = "Label — Categories"

    def __str__(self):
        return self.name


class MemberLabel(models.Model):
    """A non-exclusive tag that can be applied to members (e.g. Timezone-US, Gas).

    Unlike MemberStatus, a user can hold multiple labels simultaneously.
    Each label optionally links to an AA group — assignment adds the user to the
    group, removal takes them out.
    """

    name = models.CharField(max_length=100, unique=True)
    category = models.ForeignKey(
        LabelCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="labels",
        help_text="Groups this label with others of the same type in the UI.",
    )
    auth_group = models.OneToOneField(
        Group,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hr_member_label",
        help_text="AA group linked to this label. Members are added/removed automatically.",
    )
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    member_assignable = models.BooleanField(
        default=False,
        help_text="Allow members to assign and remove this label themselves via the member dashboard.",
    )

    class Meta:
        ordering = ["category__display_order", "category__name", "name"]
        verbose_name = "Label — Definition"
        verbose_name_plural = "Label — Definitions"

    def __str__(self):
        return self.name


class MemberLabelAssignment(models.Model):
    """Active label on a user. Multiple per user are allowed."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="hr_label_assignments",
    )
    label = models.ForeignKey(
        MemberLabel,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hr_labels_assigned",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        unique_together = [("user", "label")]
        ordering = ["label__name"]
        verbose_name = "Label — Assignment"
        verbose_name_plural = "Label — Assignments"

    def __str__(self):
        return f"{self.user} — {self.label}"


class DashboardSnooze(models.Model):
    """Suppress a member's issues from the HR dashboard issues table.

    Global — one snooze hides the member for all HR viewers.
    Expires automatically if expires_at is set; otherwise indefinite.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="hr_dashboard_snooze",
    )
    snoozed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    snoozed_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Auto-clears after this date. Leave blank for indefinite.",
    )
    note = models.TextField(help_text="Reason for snoozing this member's warnings.")

    class Meta:
        verbose_name = "Dashboard — Snooze"
        verbose_name_plural = "Dashboard — Snoozes"

    def __str__(self):
        return f"Snooze: {self.user}"


class AuditLog(models.Model):
    ACTION_RANK_ASSIGNED = "rank_assigned"
    ACTION_RANK_CHANGED = "rank_changed"
    ACTION_RANK_REMOVED = "rank_removed"
    ACTION_STATUS_SET = "status_set"
    ACTION_STATUS_CLEARED = "status_cleared"
    ACTION_LABEL_ASSIGNED = "label_assigned"
    ACTION_LABEL_REMOVED = "label_removed"
    ACTION_ROLE_ASSIGNED = "role_assigned"
    ACTION_ROLE_REMOVED = "role_removed"
    ACTION_GROUP_SYNC = "group_sync"

    ACTION_CHOICES = [
        (ACTION_RANK_ASSIGNED, "Rank assigned"),
        (ACTION_RANK_CHANGED, "Rank changed"),
        (ACTION_RANK_REMOVED, "Rank removed"),
        (ACTION_STATUS_SET, "Status set"),
        (ACTION_STATUS_CLEARED, "Status cleared"),
        (ACTION_LABEL_ASSIGNED, "Label assigned"),
        (ACTION_LABEL_REMOVED, "Label removed"),
        (ACTION_ROLE_ASSIGNED, "Role assigned"),
        (ACTION_ROLE_REMOVED, "Role removed"),
        (ACTION_GROUP_SYNC, "Group sync"),
    ]

    timestamp = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="hr_audit_log",
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    notes = models.TextField(blank=True, default="")

    # Rank fields — populated for rank_* actions
    old_rank = models.ForeignKey(
        Rank, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    new_rank = models.ForeignKey(
        Rank, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    # Status fields — populated for status_* actions
    old_status = models.CharField(max_length=20, blank=True, default="")
    new_status = models.CharField(max_length=20, blank=True, default="")

    # Label field — populated for label_* actions
    label = models.ForeignKey(
        MemberLabel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    # Role field — populated for role_* actions
    role = models.ForeignKey(
        "Role",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Audit Log Entry"
        verbose_name_plural = "Audit Log"
        indexes = [
            models.Index(fields=["user", "-timestamp"], name="hr_audit_user_ts_idx"),
        ]

    def __str__(self):
        return f"{self.get_action_display()} — {self.user} at {self.timestamp}"
