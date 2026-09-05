from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction

from allianceauth.services.hooks import get_extension_logger

from .models import (
    AuditLog,
    HrConfiguration,
    MemberLabel,
    MemberLabelAssignment,
    MemberStatusAssignment,
    Rank,
    RankAssignment,
    Role,
    RoleAssignment,
)

logger = get_extension_logger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------------
# Internal group sync helpers
# ---------------------------------------------------------------------------

def _group_add(user, group):
    if group:
        user.groups.add(group)


def _group_remove(user, group):
    if group:
        user.groups.remove(group)


def get_rank_assignment(user):
    """Return the user's current RankAssignment, or None."""
    try:
        return user.hr_rank_assignment
    except ObjectDoesNotExist:
        return None


def get_member_status(user):
    """Return the user's MemberStatusAssignment, or None."""
    try:
        return user.hr_member_status
    except ObjectDoesNotExist:
        return None


def build_alts(user, main):
    """Return list of non-main EveCharacters from the user's prefetched ownerships."""
    return [
        o.character
        for o in user.character_ownerships.all()
        if o.character and o.character.character_id != main.character_id
    ]


# ---------------------------------------------------------------------------
# Rank
# ---------------------------------------------------------------------------

def get_current_rank(user):
    """Return the user's current RankAssignment, or None."""
    return (
        RankAssignment.objects.filter(user=user)
        .select_related("rank")
        .first()
    )


def _get_rank_ids_for_user_roles(user, field):
    """Return set of Rank PKs reachable via the user's roles for the given M2M field."""
    ids = set(Role.objects.filter(assignments__user=user).values_list(field, flat=True))
    ids.discard(None)
    return ids


def get_effective_assignable_ranks(user):
    """Return queryset of Ranks this user may assign via their roles."""
    rank_ids = _get_rank_ids_for_user_roles(user, "can_assign")
    return Rank.objects.filter(pk__in=rank_ids, is_active=True).order_by("priority")


def get_effective_removable_rank_ids(user):
    """Return set of Rank PKs this user may remove via their roles."""
    return _get_rank_ids_for_user_roles(user, "can_remove")


def assign_rank(user, rank, assigned_by, notes=""):
    """Assign a rank to a user, replacing any existing rank.

    Returns the new RankAssignment, or the existing one if rank is unchanged.
    Caller is responsible for permission checks before calling.
    """
    with transaction.atomic():
        existing = (
            RankAssignment.objects.filter(user=user)
            .select_related("rank__auth_group")
            .first()
        )
        if existing and existing.rank_id == rank.pk:
            return existing

        old_rank = None
        if existing:
            old_rank = existing.rank
            _group_remove(user, old_rank.auth_group)
            existing.delete()

        new_assignment = RankAssignment.objects.create(
            user=user,
            rank=rank,
            assigned_by=assigned_by,
            notes=notes,
        )

        _group_add(user, rank.auth_group)

        action = AuditLog.ACTION_RANK_CHANGED if old_rank else AuditLog.ACTION_RANK_ASSIGNED
        AuditLog.objects.create(
            action=action,
            user=user,
            performed_by=assigned_by,
            old_rank=old_rank,
            new_rank=rank,
            notes=notes,
        )

    return new_assignment


def remove_rank(user, performed_by, notes=""):
    """Remove the current rank from a user.

    Returns True if removed, False if no current rank existed.
    Caller is responsible for permission checks before calling.
    """
    with transaction.atomic():
        existing = (
            RankAssignment.objects.filter(user=user)
            .select_related("rank__auth_group")
            .first()
        )
        if not existing:
            return False

        old_rank = existing.rank
        existing.delete()

        _group_remove(user, old_rank.auth_group)

        AuditLog.objects.create(
            action=AuditLog.ACTION_RANK_REMOVED,
            user=user,
            performed_by=performed_by,
            old_rank=old_rank,
            notes=notes,
        )

    return True


# ---------------------------------------------------------------------------
# Role
# ---------------------------------------------------------------------------

def assign_role(user, role, assigned_by):
    """Assign a role to a user. Idempotent — returns (assignment, created).

    Adds the user to role.auth_group if set and writes an audit log entry.
    """
    with transaction.atomic():
        assignment, created = RoleAssignment.objects.get_or_create(
            user=user,
            role=role,
            defaults={"assigned_by": assigned_by},
        )
        if not created:
            return assignment, False

        _group_add(user, role.auth_group)

        AuditLog.objects.create(
            action=AuditLog.ACTION_ROLE_ASSIGNED,
            user=user,
            performed_by=assigned_by,
            role=role,
        )

    return assignment, True


def remove_role(user, role, performed_by):
    """Remove a role from a user.

    Returns True if removed, False if the user did not hold the role.
    Removes the user from role.auth_group and writes an audit log entry.
    """
    with transaction.atomic():
        deleted, _ = RoleAssignment.objects.filter(user=user, role=role).delete()
        if not deleted:
            return False

        _group_remove(user, role.auth_group)

        AuditLog.objects.create(
            action=AuditLog.ACTION_ROLE_REMOVED,
            user=user,
            performed_by=performed_by,
            role=role,
        )

    return True


# ---------------------------------------------------------------------------
# Member status
# ---------------------------------------------------------------------------

def get_status_auth_group(config, status):
    """Return the AA Group for the given status string, or None."""
    if status == MemberStatusAssignment.BREAK:
        return config.break_auth_group
    if status == MemberStatusAssignment.AWAY:
        return config.away_auth_group
    return None


def set_member_status(user, status, set_by, notes=""):
    """Apply a status ('away' or 'break') to a user.

    - Swaps AA group membership.
    - Removes rank and clears roles atomically when status is Break.
    """
    config = HrConfiguration.get_solo()
    new_group = get_status_auth_group(config, status)

    with transaction.atomic():
        old_assignment = MemberStatusAssignment.objects.filter(user=user).first()
        old_status = old_assignment.status if old_assignment else ""

        if old_assignment:
            old_group = get_status_auth_group(config, old_status)
            _group_remove(user, old_group)
            old_assignment.delete()

        MemberStatusAssignment.objects.create(
            user=user,
            status=status,
            set_by=set_by,
            notes=notes,
        )

        _group_add(user, new_group)

        AuditLog.objects.create(
            action=AuditLog.ACTION_STATUS_SET,
            user=user,
            performed_by=set_by,
            old_status=old_status,
            new_status=status,
            notes=notes,
        )

        if status in MemberStatusAssignment.REMOVES_RANK:
            remove_rank(
                user,
                performed_by=set_by,
                notes=f"Rank removed: status set to '{status}'",
            )
            role_assignments = list(
                RoleAssignment.objects.filter(user=user).select_related("role__auth_group")
            )
            for ra in role_assignments:
                remove_role(user, ra.role, performed_by=set_by)


def clear_member_status(user, set_by, notes=""):
    """Clear the member's current status back to active. Returns False if no status was set."""
    config = HrConfiguration.get_solo()

    with transaction.atomic():
        assignment = MemberStatusAssignment.objects.filter(user=user).first()
        if not assignment:
            return False

        old_status = assignment.status
        _group_remove(user, get_status_auth_group(config, old_status))
        assignment.delete()

        AuditLog.objects.create(
            action=AuditLog.ACTION_STATUS_CLEARED,
            user=user,
            performed_by=set_by,
            old_status=old_status,
            notes=notes,
        )

    return True


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

def assign_label(user, label, assigned_by, notes=""):
    """Assign a label to a user and add them to the label's AA group (if any).

    Returns the MemberLabelAssignment, or the existing one if already assigned.
    """
    with transaction.atomic():
        assignment, created = MemberLabelAssignment.objects.get_or_create(
            user=user,
            label=label,
            defaults={"assigned_by": assigned_by, "notes": notes},
        )
        if not created:
            return assignment

        _group_add(user, label.auth_group)

        AuditLog.objects.create(
            action=AuditLog.ACTION_LABEL_ASSIGNED,
            user=user,
            performed_by=assigned_by,
            label=label,
            notes=notes,
        )

    return assignment


def remove_label(user, label, performed_by, notes=""):
    """Remove a label from a user and remove them from the label's AA group (if any).

    Returns True if removed, False if the user did not have the label.
    """
    with transaction.atomic():
        deleted, _ = MemberLabelAssignment.objects.filter(
            user=user, label=label
        ).delete()
        if not deleted:
            return False

        _group_remove(user, label.auth_group)

        AuditLog.objects.create(
            action=AuditLog.ACTION_LABEL_REMOVED,
            user=user,
            performed_by=performed_by,
            label=label,
            notes=notes,
        )

    return True


# ---------------------------------------------------------------------------
# Member alerts / bulk member list
# ---------------------------------------------------------------------------

@dataclass
class MemberAlerts:
    """Computed alert state for a single member.

    Raw data fields are set by compute_member_alerts. All boolean flags
    are derived properties so business rules live in exactly one place.
    """
    rank: object                        # Rank | None
    member_status: object               # MemberStatusAssignment | None
    missing_title_chars: list
    audit_issue_chars: list             # [(EveCharacter, "stale"|"missing"), ...]
    role_title_mismatches: list         # [(Role, [EveCharacter, ...]), ...]
    unentitled_rank_title_chars: list   # [(Rank, [EveCharacter, ...]), ...]
    unentitled_role_title_chars: list   # [(Role, [EveCharacter, ...]), ...]
    group_issues: list                  # [(kind, name), ...]

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    @property
    def on_status(self):
        return self.member_status.status if self.member_status else ""

    @property
    def rank_removed_by_status(self):
        """True when BREAK status caused the rank to be removed."""
        return self.on_status == MemberStatusAssignment.BREAK and not self.rank

    @property
    def title_mismatch_suppressed(self):
        """Title mismatches are not actionable while a member is on leave."""
        return self.on_status in {MemberStatusAssignment.AWAY, MemberStatusAssignment.BREAK}

    # ------------------------------------------------------------------
    # Issue flags — these are the canonical names used by views/templates
    # ------------------------------------------------------------------

    @property
    def has_no_rank_issue(self):
        return not self.rank and not self.rank_removed_by_status

    @property
    def has_title_mismatch(self):
        return bool(self.missing_title_chars) and not self.title_mismatch_suppressed

    @property
    def has_audit_issue(self):
        return bool(self.audit_issue_chars)

    @property
    def has_role_title_mismatch(self):
        return bool(self.role_title_mismatches)

    @property
    def has_unentitled_rank_title(self):
        return bool(self.unentitled_rank_title_chars)

    @property
    def has_unentitled_role_title(self):
        return bool(self.unentitled_role_title_chars)

    @property
    def has_group_issue(self):
        return bool(self.group_issues)

    @property
    def has_any_issue(self):
        return (
            self.has_no_rank_issue
            or self.has_title_mismatch
            or self.has_audit_issue
            or self.has_role_title_mismatch
            or self.has_unentitled_rank_title
            or self.has_unentitled_role_title
            or self.has_group_issue
        )


def compute_member_alerts(user, config, all_titled_roles=None, all_titled_ranks=None):
    """Return a MemberAlerts instance for a single user.

    Expects the following to be prefetched/select_related:
      - character_ownerships__character__characteraudit__characterroles__titles
      - hr_rank_assignments__rank__corp_title
      - role_assignments__role__corp_title
      - hr_member_status

    all_titled_roles: pre-fetched list of all Roles with a corp_title set.
    all_titled_ranks: pre-fetched list of all Ranks with a corp_title set.
    Pass both from prepare_members to avoid per-user queries.
    If None, each is queried here (fine for single-user views).

    For each character, every in-game title is checked against all HR-managed
    rank and role titles. If a character holds an HR-managed title they are not
    entitled to (wrong rank, role not held), it is flagged as unentitled.
    All derived booleans are computed as properties on the returned MemberAlerts.
    """
    home_corp_id = config.home_corporation_id

    current_assignment = get_rank_assignment(user)
    rank = current_assignment.rank if current_assignment else None

    member_status = get_member_status(user)

    title_corp_id = rank.corp_title.corporation_id if (rank and rank.corp_title) else None
    expected_title = rank.corp_title.title if title_corp_id else None

    try:
        main_char = user.profile.main_character
    except AttributeError:
        main_char = None
    main_char_id = main_char.character_id if main_char else None

    # Roles this user currently holds
    held_role_ids = {ra.role_id for ra in user.role_assignments.all()}

    # Roles held by user that require a corp title — check characters have it
    role_requirements = [
        (ra.role, ra.role.corp_title.title, ra.role.corp_title.corporation_id, ra.role.title_main_only)
        for ra in user.role_assignments.all()
        if ra.role.corp_title_id
    ]
    role_missing = {role: [] for role, _, _, _ in role_requirements}

    # Roles NOT held by user that have a corp title — flag if character has it anyway
    if all_titled_roles is None:
        all_titled_roles = list(
            Role.objects.filter(corp_title__isnull=False).select_related("corp_title")
        )
    unentitled_role_requirements = [
        (role, role.corp_title.title, role.corp_title.corporation_id, role.title_main_only)
        for role in all_titled_roles
        if role.pk not in held_role_ids
    ]
    unentitled_role_map = {role: [] for role, _, _, _ in unentitled_role_requirements}

    # Ranks other than the user's current rank that have a corp title —
    # flag if any character holds that title (they're not entitled to it)
    if all_titled_ranks is None:
        all_titled_ranks = list(
            Rank.objects.filter(corp_title__isnull=False).select_related("corp_title")
        )
    unentitled_rank_requirements = [
        (rank_obj, rank_obj.corp_title.title, rank_obj.corp_title.corporation_id)
        for rank_obj in all_titled_ranks
        if not rank or rank_obj.pk != rank.pk
    ]
    unentitled_rank_map = {rank_obj: [] for rank_obj, _, _ in unentitled_rank_requirements}

    missing_title_chars = []
    audit_issue_chars = []  # [(char, "stale"|"missing"), ...]

    for ownership in user.character_ownerships.all():
        char = ownership.character
        if not char:
            continue
        if home_corp_id and char.corporation_id != home_corp_id:
            continue

        is_main = char.character_id == main_char_id

        try:
            audit = char.characteraudit
            audit_ok = audit.active
        except AttributeError:
            audit = None
            audit_ok = False

        if not audit_ok:
            audit_issue_chars.append((char, "missing" if audit is None else "stale"))

        try:
            char_titles = {t.title for t in audit.characterroles.titles.all()} if audit else set()
        except AttributeError:
            char_titles = set()

        if expected_title is not None and char.corporation_id == title_corp_id:
            if expected_title not in char_titles:
                missing_title_chars.append(char)

        for role, req_title, req_corp_id, main_only in role_requirements:
            if main_only and not is_main:
                continue
            if char.corporation_id == req_corp_id and req_title not in char_titles:
                role_missing[role].append(char)

        for role, req_title, req_corp_id, main_only in unentitled_role_requirements:
            if main_only and not is_main:
                continue
            if char.corporation_id == req_corp_id and req_title in char_titles:
                unentitled_role_map[role].append(char)

        for rank_obj, title_str, corp_id in unentitled_rank_requirements:
            if char.corporation_id == corp_id and title_str in char_titles:
                unentitled_rank_map[rank_obj].append(char)

    role_title_mismatches = [(role, chars) for role, chars in role_missing.items() if chars]
    unentitled_role_title_chars = [(role, chars) for role, chars in unentitled_role_map.items() if chars]
    unentitled_rank_title_chars = [(rank_obj, chars) for rank_obj, chars in unentitled_rank_map.items() if chars]

    # Group sync check — detect HR assignments whose auth_group is missing from user.groups
    user_group_ids = {g.pk for g in user.groups.all()}
    group_issues = []

    if rank and rank.auth_group_id and rank.auth_group_id not in user_group_ids:
        group_issues.append(("rank", rank.name))

    for ra in user.role_assignments.all():
        if ra.role.auth_group_id and ra.role.auth_group_id not in user_group_ids:
            group_issues.append(("role", ra.role.name))

    for la in user.hr_label_assignments.all():
        if la.label.auth_group_id and la.label.auth_group_id not in user_group_ids:
            group_issues.append(("label", la.label.name))

    if member_status:
        if member_status.status == MemberStatusAssignment.BREAK:
            status_group_id = config.break_auth_group_id
        elif member_status.status == MemberStatusAssignment.AWAY:
            status_group_id = config.away_auth_group_id
        else:
            status_group_id = None
        if status_group_id and status_group_id not in user_group_ids:
            group_issues.append(("status", member_status.get_status_display()))

    return MemberAlerts(
        rank=rank,
        member_status=member_status,
        missing_title_chars=missing_title_chars,
        audit_issue_chars=audit_issue_chars,
        role_title_mismatches=role_title_mismatches,
        unentitled_rank_title_chars=unentitled_rank_title_chars,
        unentitled_role_title_chars=unentitled_role_title_chars,
        group_issues=group_issues,
    )


def prepare_members(config):
    """Return list of member dicts for all users in config.aa_state.

    If config.home_corp is set, only users whose main character is in that
    corporation are included, and character-level checks (title, audit) are
    restricted to that corporation's characters.
    """
    if not config.aa_state:
        return []

    home_corp_id = config.home_corporation_id

    users = (
        User.objects.filter(profile__state=config.aa_state)
        .select_related(
            "profile__main_character",
            "hr_member_status",
            "hr_rank_assignment__rank__corp_title",
        )
        .prefetch_related(
            "character_ownerships__character__characteraudit__characterroles__titles",
            "role_assignments__role__corp_title",
            "hr_label_assignments__label",
            "groups",
        )
    )

    if home_corp_id:
        users = users.filter(profile__main_character__corporation_id=home_corp_id)

    # Fetch once — passed to each compute_member_alerts call to avoid per-user queries
    all_titled_roles = list(
        Role.objects.filter(corp_title__isnull=False).select_related("corp_title")
    )
    all_titled_ranks = list(
        Rank.objects.filter(corp_title__isnull=False).select_related("corp_title")
    )

    members = []
    for user in users:
        try:
            main = user.profile.main_character
        except AttributeError:
            main = None
        if not main:
            continue

        alts = build_alts(user, main)

        alerts = compute_member_alerts(user, config, all_titled_roles=all_titled_roles, all_titled_ranks=all_titled_ranks)
        labels = [a.label for a in user.hr_label_assignments.all()]

        # Resolve the main character via the prefetched ownerships so the template
        # can access characteraudit/characterroles/titles without extra DB queries.
        main_titles = []
        for o in user.character_ownerships.all():
            if o.character and o.character.character_id == main.character_id:
                try:
                    main_titles = list(o.character.characteraudit.characterroles.titles.all())
                except AttributeError:
                    pass
                break

        members.append({
            "user": user,
            "main": main,
            "alts": alts,
            "alt_count": len(alts),
            "alerts": alerts,
            "labels": labels,
            "main_titles": main_titles,
        })

    members.sort(key=lambda m: m["main"].character_name)
    return members


def fix_groups(user, performed_by):
    """Reconcile HR group memberships and queue corptools character refresh.

    Adds groups missing from user.groups that current HR assignments require,
    and removes HR-managed groups the user holds but no longer qualifies for.
    Also queues a corptools + AA EVE character update for every owned character.

    Returns (added, removed) — lists of (kind, name) tuples.
    """
    from django.contrib.auth.models import Group as AuthGroup
    from allianceauth.eveonline.tasks import update_character as aa_update_character
    from corptools.tasks.character import update_character as ct_update_character

    config = HrConfiguration.get_solo()
    user_group_ids = set(user.groups.values_list("pk", flat=True))

    # Groups required by current active HR assignments
    expected = {}  # group_id -> (kind, display_name)

    rank_assignment = (
        RankAssignment.objects.filter(user=user)
        .select_related("rank__auth_group")
        .first()
    )
    if rank_assignment and rank_assignment.rank.auth_group_id:
        expected[rank_assignment.rank.auth_group_id] = ("rank", rank_assignment.rank.name)

    for ra in RoleAssignment.objects.filter(user=user).select_related("role__auth_group"):
        if ra.role.auth_group_id:
            expected[ra.role.auth_group_id] = ("role", ra.role.name)

    for la in MemberLabelAssignment.objects.filter(user=user).select_related("label__auth_group"):
        if la.label.auth_group_id:
            expected[la.label.auth_group_id] = ("label", la.label.name)

    status_assignment = MemberStatusAssignment.objects.filter(user=user).first()
    if status_assignment:
        status_group = get_status_auth_group(config, status_assignment.status)
        if status_group:
            expected[status_group.pk] = ("status", status_assignment.get_status_display())

    # All group IDs HR manages (so we only touch groups HR owns)
    managed_ids = set()
    managed_ids.update(Rank.objects.filter(auth_group__isnull=False).values_list("auth_group_id", flat=True))
    managed_ids.update(Role.objects.filter(auth_group__isnull=False).values_list("auth_group_id", flat=True))
    managed_ids.update(MemberLabel.objects.filter(auth_group__isnull=False).values_list("auth_group_id", flat=True))
    if config.away_auth_group_id:
        managed_ids.add(config.away_auth_group_id)
    if config.break_auth_group_id:
        managed_ids.add(config.break_auth_group_id)

    added = []
    removed = []

    missing_ids = set(expected) - user_group_ids
    if missing_ids:
        groups = list(AuthGroup.objects.filter(pk__in=missing_ids))
        user.groups.add(*groups)
        added = [expected[g.pk] for g in groups]

    stale_ids = (user_group_ids & managed_ids) - set(expected)
    if stale_ids:
        groups = list(AuthGroup.objects.filter(pk__in=stale_ids))
        stale_names = {g.pk: g.name for g in groups}
        user.groups.remove(*groups)
        removed = [("group", stale_names[gid]) for gid in stale_ids]

    if added or removed:
        parts = []
        if added:
            parts.append("added: " + ", ".join(f"{k} '{n}'" for k, n in added))
        if removed:
            parts.append("removed: " + ", ".join(f"'{n}'" for _, n in removed))
        AuditLog.objects.create(
            action=AuditLog.ACTION_GROUP_SYNC,
            user=user,
            performed_by=performed_by,
            notes="Group sync: " + "; ".join(parts),
        )
        logger.info("Group sync for %s: added=%d removed=%d", user, len(added), len(removed))

    char_ids = list(
        user.character_ownerships.values_list("character__character_id", flat=True)
    )
    for char_id in char_ids:
        ct_update_character.apply_async(args=[char_id], kwargs={"force_refresh": True}, priority=4)
        aa_update_character.apply_async(args=[char_id], priority=4)

    return added, removed


def get_main_left_corp_members(config):
    """Return list of member dicts for users who have an alt in the home corp
    but whose main character is not.

    This identifies accounts where the registered main has left or been moved
    out of the home corp while corp alts remain — an actionable membership issue.
    Returns an empty list when home_corp is not configured.
    """
    if not config.aa_state or not config.home_corporation_id:
        return []

    home_corp_id = config.home_corporation_id

    users = (
        User.objects.filter(profile__state=config.aa_state)
        .filter(profile__main_character__isnull=False)
        .exclude(profile__main_character__corporation_id=home_corp_id)
        .filter(character_ownerships__character__corporation_id=home_corp_id)
        .distinct()
        .select_related("profile__main_character", "hr_rank_assignment__rank")
    )

    results = []
    for user in users:
        main = user.profile.main_character
        assignment = get_rank_assignment(user)
        results.append({
            "user": user,
            "main": main,
            "rank": assignment.rank if assignment else None,
        })

    results.sort(key=lambda m: m["main"].character_name)
    return results
