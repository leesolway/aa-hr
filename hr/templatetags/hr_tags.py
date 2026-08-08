from django import template

register = template.Library()

EVE_IMAGE_BASE = "https://images.evetech.net"


@register.simple_tag
def eve_image(category, entity_id, size=32):
    if category == "character":
        return f"{EVE_IMAGE_BASE}/characters/{entity_id}/portrait?size={size}"
    elif category == "corporation":
        return f"{EVE_IMAGE_BASE}/corporations/{entity_id}/logo?size={size}"
    elif category == "alliance":
        return f"{EVE_IMAGE_BASE}/alliances/{entity_id}/logo?size={size}"
    return ""


@register.simple_tag
def zkillboard_url(character_id):
    return f"https://zkillboard.com/character/{character_id}/"


@register.simple_tag
def evewho_url(character_id):
    return f"https://evewho.com/character/{character_id}"


@register.filter
def is_in(value, collection):
    """Return True if value is in collection. Usage: {{ pk|is_in:current_label_ids }}"""
    return value in collection
