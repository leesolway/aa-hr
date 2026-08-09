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


def current_assignment_from_prefetch(assignments):
    """Return the current RankAssignment from a prefetched iterable, or None."""
    return next((a for a in assignments if a.is_current), None)


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
        RankAssignment.objects.filter(user=user, is_current=True)
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
            RankAssignment.objects.filter(user=user, is_current=True)
            .select_related("rank__auth_group")
            .first()
        )
        if existing and existing.rank_id == rank.pk:
            return existing

        old_rank = None
        if existing:
            old_rank = existing.rank
            _group_remove(user, old_rank.auth_group)
            existing.is_current = False
            existing.save(update_fields=["is_current"])

        new_assignment = RankAssignment.objects.create(
            user=user,
            rank=rank,
            assigned_by=assigned_by,
            notes=notes,
            is_current=True,
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
            RankAssignment.objects.filter(user=user, is_current=True)
            .select_related("rank__auth_group")
            .first()
        )
        if not existing:
            return False

        old_rank = existing.rank
        existing.is_current = False
        existing.save(update_fields=["is_current"])

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

def compute_member_alerts(user, config, all_titled_roles=None):
    """Return alert dict for a single user.

    Expects the following to be prefetched/select_related:
      - character_ownerships__character__characteraudit__characterroles__titles
      - hr_rank_assignments__rank__corp_title
      - role_assignments__role__corp_title
      - hr_member_status

    all_titled_roles: optional pre-fetched list of all Role objects that have a
    corp_title set. Pass this from prepare_members to avoid per-user queries.
    If None, it is queried here (fine for single-user views).

    Performs a single pass over character_ownerships.
    audit_issue_chars is a list of (char, "stale"|"missing") tuples.
    title_mismatch is suppressed (False) when the user is on any active status.
    role_title_mismatches: list of (role, [chars_missing_title]) — roles held but title absent.
    stale_role_title_chars: list of (role, [chars_with_title]) — title present but role not held.
    """
    home_corp_id = config.home_corporation_id

    current_assignment = current_assignment_from_prefetch(user.hr_rank_assignments.all())
    rank = current_assignment.rank if current_assignment else None

    member_status = get_member_status(user)
    on_status = member_status.status if member_status else ""
    rank_removed_by_status = bool(on_status == MemberStatusAssignment.BREAK and not rank)

    title_corp_id = rank.corp_title.corporation_id if (rank and rank.corp_title) else None
    expected_title = rank.corp_title.title if title_corp_id else None

    prev_title = None
    prev_corp_id = None
    if not rank:
        prev_assignment = next(
            (a for a in user.hr_rank_assignments.all() if not a.is_current), None
        )
        if prev_assignment and prev_assignment.rank.corp_title_id:
            prev_corp_id = prev_assignment.rank.corp_title.corporation_id
            prev_title = prev_assignment.rank.corp_title.title

    # Roles this user currently holds
    held_role_ids = {ra.role_id for ra in user.role_assignments.all()}

    # Roles held by user that require a corp title — check characters have it
    role_requirements = [
        (ra.role, ra.role.corp_title.title, ra.role.corp_title.corporation_id)
        for ra in user.role_assignments.all()
        if ra.role.corp_title_id
    ]
    role_missing = {role: [] for role, _, _ in role_requirements}

    # Roles NOT held by user that have a corp title — flag if character has it anyway
    if all_titled_roles is None:
        all_titled_roles = list(
            Role.objects.filter(corp_title__isnull=False).select_related("corp_title")
        )
    unattained_role_requirements = [
        (role, role.corp_title.title, role.corp_title.corporation_id)
        for role in all_titled_roles
        if role.pk not in held_role_ids
    ]
    stale_role_map = {role: [] for role, _, _ in unattained_role_requirements}

    missing_title_chars = []
    audit_issue_chars = []  # [(char, "stale"|"missing"), ...]
    stale_title_chars = []

    for ownership in user.character_ownerships.all():
        char = ownership.character
        if not char:
            continue
        if home_corp_id and char.corporation_id != home_corp_id:
            continue

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

        if prev_title is not None and char.corporation_id == prev_corp_id:
            if prev_title in char_titles:
                stale_title_chars.append(char)

        for role, req_title, req_corp_id in role_requirements:
            if char.corporation_id == req_corp_id and req_title not in char_titles:
                role_missing[role].append(char)

        for role, req_title, req_corp_id in unattained_role_requirements:
            if char.corporation_id == req_corp_id and req_title in char_titles:
                stale_role_map[role].append(char)

    role_title_mismatches = [(role, chars) for role, chars in role_missing.items() if chars]
    stale_role_title_chars = [(role, chars) for role, chars in stale_role_map.items() if chars]

    return {
        "rank": rank,
        "title_mismatch": bool(missing_title_chars) and on_status not in {MemberStatusAssignment.AWAY, MemberStatusAssignment.BREAK},
        "missing_title_chars": missing_title_chars,
        "stale_title_chars": stale_title_chars,
        "audit_issue_chars": audit_issue_chars,
        "has_audit_issue": bool(audit_issue_chars),
        "member_status": member_status,
        "rank_removed_by_status": rank_removed_by_status,
        "role_title_mismatches": role_title_mismatches,
        "has_role_title_mismatch": bool(role_title_mismatches),
        "stale_role_title_chars": stale_role_title_chars,
        "has_stale_role_title": bool(stale_role_title_chars),
    }


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
        .select_related("profile__main_character", "hr_member_status")
        .prefetch_related(
            "character_ownerships__character__characteraudit__characterroles__titles",
            "hr_rank_assignments__rank__corp_title",
            "role_assignments__role__corp_title",
            "hr_label_assignments__label",
        )
    )

    if home_corp_id:
        users = users.filter(profile__main_character__corporation_id=home_corp_id)

    # Fetch once — passed to each compute_member_alerts call to avoid per-user queries
    all_titled_roles = list(
        Role.objects.filter(corp_title__isnull=False).select_related("corp_title")
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

        alerts = compute_member_alerts(user, config, all_titled_roles=all_titled_roles)
        labels = [a.label for a in user.hr_label_assignments.all()]

        members.append({
            "user": user,
            "main": main,
            "alts": alts,
            "alt_count": len(alts),
            **alerts,
            "labels": labels,
        })

    members.sort(key=lambda m: m["main"].character_name)
    return members


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
        .select_related("profile__main_character")
        .prefetch_related("hr_rank_assignments__rank")
    )

    results = []
    for user in users:
        main = user.profile.main_character
        current = current_assignment_from_prefetch(user.hr_rank_assignments.all())
        results.append({
            "user": user,
            "main": main,
            "rank": current.rank if current else None,
        })

    results.sort(key=lambda m: m["main"].character_name)
    return results
