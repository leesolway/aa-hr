from allianceauth.authentication.signals import state_changed
from allianceauth.services.hooks import get_extension_logger
from django.dispatch import receiver

logger = get_extension_logger(__name__)


@receiver(state_changed)
def remove_rank_on_state_loss(sender, user, state, **kwargs):
    """Remove rank when a user leaves the configured HR state."""
    from .models import HrConfiguration, RankAssignment
    from .services import remove_rank

    config = HrConfiguration.get_solo()
    if not config.aa_state:
        return

    if state.pk == config.aa_state_id:
        return  # still in the correct state

    if not RankAssignment.objects.filter(user=user, is_current=True).exists():
        return

    logger.info(
        "Removing rank from %s due to state change to '%s'", user, state
    )
    remove_rank(user, performed_by=None, notes=f"Automatic removal: state changed to '{state}'")
