from django.contrib.auth import get_user_model
from django.db import transaction

from allianceauth.services.hooks import get_extension_logger

from .models import Role, RoleAssignment, Rank, RankAssignment, RankAuditLog

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

        action = RankAuditLog.ACTION_CHANGED if old_rank else RankAuditLog.ACTION_ASSIGNED
        RankAuditLog.objects.create(
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

        RankAuditLog.objects.create(
            action=RankAuditLog.ACTION_REMOVED,
            user=user,
            performed_by=performed_by,
            old_rank=old_rank,
            new_rank=None,
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
        .select_related("profile__main_character")
        .prefetch_related(
            "character_ownerships__character__characteraudit__characterroles__titles",
            "hr_rank_assignments__rank",
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

        members.append(
            {
                "user": user,
                "main": main,
                "alts": alts,
                "alt_count": len(alts),
                "rank": rank,
                "title_mismatch": bool(missing_title_chars),
                "missing_title_chars": missing_title_chars,
                "audit_issue_chars": audit_issue_chars,
                "has_audit_issue": bool(audit_issue_chars),
            }
        )

    members.sort(key=lambda m: m["main"].character_name)
    return members
