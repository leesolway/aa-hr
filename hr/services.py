from django.contrib.auth import get_user_model
from django.db import transaction

from allianceauth.services.hooks import get_extension_logger

from .models import (
    AuditLog,
    MemberLabel,
    MemberLabelAssignment,
    MemberStatus,
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


def get_effective_assignable_ranks(user):
    """Return queryset of Ranks this user may assign via their roles."""
    role_ids = RoleAssignment.objects.filter(user=user).values_list(
        "role_id", flat=True
    )
    rank_ids = set(
        Role.objects.filter(pk__in=role_ids).values_list("can_assign", flat=True)
    )
    rank_ids.discard(None)
    return Rank.objects.filter(pk__in=rank_ids, is_active=True).order_by("priority")


def get_effective_removable_rank_ids(user):
    """Return set of Rank PKs this user may remove via their roles."""
    role_ids = RoleAssignment.objects.filter(user=user).values_list(
        "role_id", flat=True
    )
    ids = set(
        Role.objects.filter(pk__in=role_ids).values_list("can_remove", flat=True)
    )
    ids.discard(None)
    return ids


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


def set_member_status(user, status, set_by, notes=""):
    """Apply a status to a user.

    - Removes any existing status group from the user.
    - Adds the new status group (if any).
    - Removes rank atomically if status.removes_rank is True.
    """
    with transaction.atomic():
        old_assignment = (
            MemberStatusAssignment.objects.filter(user=user)
            .select_related("status__auth_group")
            .first()
        )
        old_status = old_assignment.status if old_assignment else None

        if old_assignment:
            if old_status.auth_group:
                user.groups.remove(old_status.auth_group)
            old_assignment.delete()

        MemberStatusAssignment.objects.create(
            user=user,
            status=status,
            set_by=set_by,
            notes=notes,
        )

        if status.auth_group:
            user.groups.add(status.auth_group)

        AuditLog.objects.create(
            action=AuditLog.ACTION_STATUS_SET,
            user=user,
            performed_by=set_by,
            old_status=old_status,
            new_status=status,
            notes=notes,
        )

        if status.removes_rank:
            remove_rank(
                user,
                performed_by=set_by,
                notes=f"Rank removed: member status set to '{status}'",
            )
            removed_count, _ = RoleAssignment.objects.filter(user=user).delete()
            if removed_count:
                AuditLog.objects.create(
                    action=AuditLog.ACTION_ROLES_CLEARED,
                    user=user,
                    performed_by=set_by,
                    notes=f"{removed_count} role(s) cleared: member status set to '{status}'",
                )


def clear_member_status(user, set_by, notes=""):
    """Clear the member's current status back to normal. Returns False if no status was set."""
    with transaction.atomic():
        assignment = (
            MemberStatusAssignment.objects.filter(user=user)
            .select_related("status__auth_group")
            .first()
        )
        if not assignment:
            return False

        old_status = assignment.status
        if old_status.auth_group:
            user.groups.remove(old_status.auth_group)
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


def characters_missing_title(user, rank):
    """Return list of EveCharacter objects that do not have rank.corp_title."""
    if not rank.corp_title:
        return []
    expected = rank.corp_title.title
    missing = []
    for ownership in user.character_ownerships.all():
        char = ownership.character
        if not char:
            continue
        try:
            titles = {t.title for t in char.characteraudit.characterroles.titles.all()}
        except AttributeError:
            titles = set()
        if expected not in titles:
            missing.append(char)
    return missing


def prepare_members(config):
    """Return list of member dicts for all users in config.aa_state."""
    if not config.aa_state:
        return []

    users = (
        User.objects.filter(profile__state=config.aa_state)
        .select_related("profile__main_character", "hr_member_status__status")
        .prefetch_related(
            "character_ownerships__character__characteraudit__characterroles__titles",
            "hr_rank_assignments__rank",
            "hr_label_assignments__label",
        )
    )

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

        current_assignment = next(
            (a for a in user.hr_rank_assignments.all() if a.is_current), None
        )
        rank = current_assignment.rank if current_assignment else None

        missing_title_chars = []
        audit_issue_chars = []
        expected = rank.corp_title.title if (rank and rank.corp_title) else None

        for ownership in user.character_ownerships.all():
            char = ownership.character
            if not char:
                continue
            try:
                audit = char.characteraudit
                if not audit.active:
                    audit_issue_chars.append(char)
                if expected is not None:
                    titles = {t.title for t in audit.characterroles.titles.all()}
                    if expected not in titles:
                        missing_title_chars.append(char)
            except AttributeError:
                audit_issue_chars.append(char)
                if expected is not None:
                    missing_title_chars.append(char)

        try:
            member_status = user.hr_member_status
        except Exception:
            member_status = None

        on_status = member_status.status if member_status else None
        is_on_break = bool(on_status and on_status.removes_rank)
        # Suppress title mismatch warnings for members on any status — not actionable
        title_mismatch = bool(missing_title_chars) and not on_status

        labels = [a.label for a in user.hr_label_assignments.all()]

        members.append(
            {
                "user": user,
                "main": main,
                "alts": alts,
                "alt_count": len(alts),
                "rank": rank,
                "title_mismatch": title_mismatch,
                "missing_title_chars": missing_title_chars,
                "audit_issue_chars": audit_issue_chars,
                "has_audit_issue": bool(audit_issue_chars),
                "member_status": member_status,
                "is_on_break": is_on_break,
                "labels": labels,
            }
        )

    members.sort(key=lambda m: m["main"].character_name)
    return members
