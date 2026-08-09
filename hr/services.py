from django.contrib.auth import get_user_model
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


def get_current_rank(user):
    """Return the user's current RankAssignment, or None."""
    return (
        RankAssignment.objects.filter(user=user, is_current=True)
        .select_related("rank")
        .first()
    )


def _get_rank_ids_for_user_roles(user, field):
    """Return set of Rank PKs reachable via the user's roles for the given M2M field."""
    role_ids = RoleAssignment.objects.filter(user=user).values_list("role_id", flat=True)
    ids = set(Role.objects.filter(pk__in=role_ids).values_list(field, flat=True))
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
            if old_rank.auth_group:
                user.groups.remove(old_rank.auth_group)
            existing.is_current = False
            existing.save(update_fields=["is_current"])

        new_assignment = RankAssignment.objects.create(
            user=user,
            rank=rank,
            assigned_by=assigned_by,
            notes=notes,
            is_current=True,
        )

        if rank.auth_group:
            user.groups.add(rank.auth_group)

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

        if old_rank.auth_group:
            user.groups.remove(old_rank.auth_group)

        AuditLog.objects.create(
            action=AuditLog.ACTION_RANK_REMOVED,
            user=user,
            performed_by=performed_by,
            old_rank=old_rank,
            notes=notes,
        )

    return True


def _status_auth_group(config, status):
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
    new_group = _status_auth_group(config, status)

    with transaction.atomic():
        old_assignment = MemberStatusAssignment.objects.filter(user=user).first()
        old_status = old_assignment.status if old_assignment else ""

        if old_assignment:
            old_group = _status_auth_group(config, old_status)
            if old_group:
                user.groups.remove(old_group)
            old_assignment.delete()

        MemberStatusAssignment.objects.create(
            user=user,
            status=status,
            set_by=set_by,
            notes=notes,
        )

        if new_group:
            user.groups.add(new_group)

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
            removed_count, _ = RoleAssignment.objects.filter(user=user).delete()
            if removed_count:
                AuditLog.objects.create(
                    action=AuditLog.ACTION_ROLES_CLEARED,
                    user=user,
                    performed_by=set_by,
                    notes=f"{removed_count} role(s) cleared: status set to '{status}'",
                )


def clear_member_status(user, set_by, notes=""):
    """Clear the member's current status back to active. Returns False if no status was set."""
    config = HrConfiguration.get_solo()

    with transaction.atomic():
        assignment = MemberStatusAssignment.objects.filter(user=user).first()
        if not assignment:
            return False

        old_status = assignment.status
        old_group = _status_auth_group(config, old_status)
        if old_group:
            user.groups.remove(old_group)
        assignment.delete()

        AuditLog.objects.create(
            action=AuditLog.ACTION_STATUS_CLEARED,
            user=user,
            performed_by=set_by,
            old_status=old_status,
            notes=notes,
        )

    return True


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

        if label.auth_group:
            user.groups.add(label.auth_group)

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

        if label.auth_group:
            user.groups.remove(label.auth_group)

        AuditLog.objects.create(
            action=AuditLog.ACTION_LABEL_REMOVED,
            user=user,
            performed_by=performed_by,
            label=label,
            notes=notes,
        )

    return True


def compute_member_alerts(user, config):
    """Return alert dict for a single user.

    Expects character_ownerships__character__characteraudit__characterroles__titles,
    hr_rank_assignments__rank__corp_title, and hr_member_status__status to be
    prefetched/select_related. Performs a single pass over character_ownerships.

    audit_issue_chars is a list of (char, "stale"|"missing") tuples.
    title_mismatch is suppressed (False) when the user is on any active status.
    """
    home_corp_id = config.home_corp.corporation_id if config.home_corp_id else None

    current_assignment = next(
        (a for a in user.hr_rank_assignments.all() if a.is_current), None
    )
    rank = current_assignment.rank if current_assignment else None

    try:
        member_status = user.hr_member_status
    except Exception:
        member_status = None
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

    return {
        "rank": rank,
        "title_mismatch": bool(missing_title_chars) and not on_status,  # suppressed when on any status
        "missing_title_chars": missing_title_chars,
        "stale_title_chars": stale_title_chars,
        "audit_issue_chars": audit_issue_chars,
        "has_audit_issue": bool(audit_issue_chars),
        "member_status": member_status,
        "rank_removed_by_status": rank_removed_by_status,
    }


def prepare_members(config):
    """Return list of member dicts for all users in config.aa_state.

    If config.home_corp is set, only users whose main character is in that
    corporation are included, and character-level checks (title, audit) are
    restricted to that corporation's characters.
    """
    if not config.aa_state:
        return []

    home_corp_id = config.home_corp.corporation_id if config.home_corp_id else None

    users = (
        User.objects.filter(profile__state=config.aa_state)
        .select_related("profile__main_character", "hr_member_status")
        .prefetch_related(
            "character_ownerships__character__characteraudit__characterroles__titles",
            "hr_rank_assignments__rank__corp_title",
            "hr_label_assignments__label",
        )
    )

    if home_corp_id:
        users = users.filter(profile__main_character__corporation_id=home_corp_id)

    members = []
    for user in users:
        try:
            main = user.profile.main_character
        except AttributeError:
            main = None
        if not main:
            continue

        alts = [
            o.character
            for o in user.character_ownerships.all()
            if o.character and o.character.character_id != main.character_id
        ]

        alerts = compute_member_alerts(user, config)
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
