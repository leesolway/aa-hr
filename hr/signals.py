from allianceauth.authentication.signals import state_changed
from allianceauth.services.hooks import get_extension_logger
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

logger = get_extension_logger(__name__)


@receiver(state_changed)
def remove_rank_on_state_loss(sender, user, state, **kwargs):
    """Remove rank, roles, labels, and status when a user leaves the configured HR state."""
    from .models import HrConfiguration, MemberLabelAssignment, RankAssignment, RoleAssignment
    from .services import clear_member_status, remove_label, remove_rank, remove_role

    config = HrConfiguration.get_solo()
    if not config.aa_state:
        return

    if state.pk == config.aa_state_id:
        return  # still in the correct state

    note = f"Automatic removal: state changed to '{state}'"

    if RankAssignment.objects.filter(user=user, is_current=True).exists():
        logger.info("Removing rank from %s due to state change to '%s'", user, state)
        remove_rank(user, performed_by=None, notes=note)

    role_assignments = list(RoleAssignment.objects.filter(user=user).select_related("role__auth_group"))
    for ra in role_assignments:
        remove_role(user, ra.role, performed_by=None)
    if role_assignments:
        logger.info("Removed %d role(s) from %s due to state change to '%s'", len(role_assignments), user, state)

    label_assignments = list(MemberLabelAssignment.objects.filter(user=user).select_related("label__auth_group"))
    for la in label_assignments:
        remove_label(user, la.label, performed_by=None, notes=note)
    if label_assignments:
        logger.info("Removed %d label(s) from %s due to state change to '%s'", len(label_assignments), user, state)

    if clear_member_status(user, set_by=None, notes=note):
        logger.info("Cleared status for %s due to state change to '%s'", user, state)


@receiver(m2m_changed)
def sync_group_removal(sender, instance, action, pk_set, **kwargs):
    """When AA groups are removed from a user externally, clean up HR assignments.

    This keeps HR state consistent when groups are revoked outside the HR UI
    (e.g. via AA admin or another service).
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    if sender is not User.groups.through:
        return
    if action != "post_remove" or not pk_set:
        return

    from .models import AuditLog, HrConfiguration, MemberLabelAssignment, MemberStatusAssignment, RankAssignment, RoleAssignment
    from .services import get_status_auth_group, remove_rank

    # m2m_changed fires for both user.groups.remove() and group.user_set.remove().
    # When called from the group side (e.g. AA admin), instance is the Group and
    # pk_set contains User PKs. Normalise to (user, group_pk_set) pairs.
    if isinstance(instance, User):
        user_group_pairs = [(instance, pk_set)]
    else:
        group_pk_set = {instance.pk}
        user_group_pairs = [
            (user, group_pk_set)
            for user in User.objects.filter(pk__in=pk_set)
        ]

    for user, group_pk_set in user_group_pairs:
        # Remove label assignments whose group was revoked externally
        affected_labels = list(
            MemberLabelAssignment.objects.filter(
                user=user,
                label__auth_group__in=group_pk_set,
            ).select_related("label")
        )
        if affected_labels:
            label_ids = [a.label_id for a in affected_labels]
            MemberLabelAssignment.objects.filter(user=user, label_id__in=label_ids).delete()
            AuditLog.objects.bulk_create([
                AuditLog(
                    action=AuditLog.ACTION_LABEL_REMOVED,
                    user=user,
                    performed_by=None,
                    label=a.label,
                    notes="Automatic removal: group revoked externally",
                )
                for a in affected_labels
            ])
            logger.info(
                "Removed %d label assignment(s) from %s due to external group removal",
                len(affected_labels), user,
            )

        # Clear status if its group was revoked externally
        config = HrConfiguration.get_solo()
        status_to_clear = None
        for status_val in (MemberStatusAssignment.AWAY, MemberStatusAssignment.BREAK):
            grp = get_status_auth_group(config, status_val)
            if grp and grp.pk in group_pk_set:
                status_to_clear = status_val
                break
        if status_to_clear:
            status_assignment = MemberStatusAssignment.objects.filter(
                user=user, status=status_to_clear
            ).first()
            if status_assignment:
                status_assignment.delete()
                AuditLog.objects.create(
                    action=AuditLog.ACTION_STATUS_CLEARED,
                    user=user,
                    performed_by=None,
                    old_status=status_to_clear,
                    notes="Automatic removal: group revoked externally",
                )
                logger.info(
                    "Cleared status '%s' from %s due to external group removal",
                    status_to_clear, user,
                )

        # Remove role assignments whose group was revoked externally
        affected_roles = list(
            RoleAssignment.objects.filter(
                user=user,
                role__auth_group__in=group_pk_set,
            ).select_related("role")
        )
        if affected_roles:
            role_ids = [ra.role_id for ra in affected_roles]
            RoleAssignment.objects.filter(user=user, role_id__in=role_ids).delete()
            AuditLog.objects.bulk_create([
                AuditLog(
                    action=AuditLog.ACTION_ROLE_REMOVED,
                    user=user,
                    performed_by=None,
                    role=ra.role,
                    notes="Automatic removal: group revoked externally",
                )
                for ra in affected_roles
            ])
            logger.info(
                "Removed %d role assignment(s) from %s due to external group removal",
                len(affected_roles), user,
            )

        # Remove rank if its auth_group was revoked externally.
        # RankAssignment is marked is_current=False before _group_remove fires inside
        # remove_rank(), so the query below returns None on any re-entrant signal call.
        rank_assignment = (
            RankAssignment.objects.filter(
                user=user,
                is_current=True,
                rank__auth_group__in=group_pk_set,
            )
            .select_related("rank")
            .first()
        )
        if rank_assignment:
            remove_rank(user, performed_by=None, notes="Automatic removal: group revoked externally")
            logger.info(
                "Removed rank from %s due to external removal of rank group",
                user,
            )
