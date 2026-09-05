from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

from allianceauth.services.hooks import get_extension_logger

from .models import HrConfiguration, MemberStatusAssignment
from .services import set_member_status

logger = get_extension_logger(__name__)
User = get_user_model()


@shared_task
def check_member_inactivity():
    """Set Inactive status on members whose most recent EVE login exceeds the threshold.

    Reads inactivity_threshold_days from HrConfiguration. Skips members who already
    have any non-active status (manually set statuses are never overridden).
    Requires corptools CharacterAudit.last_known_login to be populated.
    """
    config = HrConfiguration.get_solo()

    if not config.inactivity_threshold_days:
        logger.debug("check_member_inactivity: no threshold configured, skipping.")
        return

    if not config.aa_state:
        logger.debug("check_member_inactivity: no state configured, skipping.")
        return

    cutoff = timezone.now() - timezone.timedelta(days=config.inactivity_threshold_days)

    users = (
        User.objects.filter(profile__state=config.aa_state)
        .filter(profile__main_character__isnull=False)
        .exclude(hr_member_status__isnull=False)  # skip anyone already on a status
        .prefetch_related(
            "character_ownerships__character__characteraudit"
        )
    )

    if config.home_corporation_id:
        users = users.filter(
            profile__main_character__corporation_id=config.home_corporation_id
        )

    set_count = 0

    for user in users:
        logins = []
        for ownership in user.character_ownerships.all():
            char = ownership.character
            if not char:
                continue
            try:
                login = char.characteraudit.last_known_login
                if login:
                    logins.append(login)
            except AttributeError:
                pass

        if not logins:
            # No login data available — skip rather than falsely flagging
            continue

        most_recent = max(logins)
        if most_recent < cutoff:
            label = config.inactive_label
            set_member_status(
                user,
                status=MemberStatusAssignment.INACTIVE,
                set_by=None,
                notes=f"Auto-applied: last EVE login {most_recent.date()} exceeds {config.inactivity_threshold_days}-day threshold.",
            )
            logger.info(
                "check_member_inactivity: set %s on %s (last login %s)",
                label,
                user,
                most_recent.date(),
            )
            set_count += 1

    logger.info("check_member_inactivity: complete — %d member(s) set to Inactive.", set_count)
    return set_count
