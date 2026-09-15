from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()

UNIT_NAMES = {
    "coil": ("coil", "coils"),
    "metre": ("metre", "metres"),
    "piece": ("piece", "pieces"),
    "pack": ("pack", "packs"),
    "box": ("box", "boxes"),
    "roll": ("roll", "rolls"),
    "length": ("length", "lengths"),
    "set": ("set", "sets"),
}


def _decimal(value):
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _plain(value):
    """Group thousands and drop trailing zeros: 30.00 -> "30", 1250.50 -> "1,250.5"."""
    return f"{_decimal(value).normalize():,f}"


@register.filter
def naira(value):
    """33000 -> "33,000.00"."""
    return f"{_decimal(value):,.2f}"


@register.filter
def naira_or_dash(value):
    return naira(value) if _decimal(value) else "-"


@register.filter
def quantity(value, unit=""):
    """69 with unit "coil" -> "69 coils"; without a unit just the number."""
    text = _plain(value)
    if unit in UNIT_NAMES:
        singular, plural = UNIT_NAMES[unit]
        text = f"{text} {singular if _decimal(value) == 1 else plural}"
    return text


@register.filter
def percent(value):
    return f"{_plain(value)}%"


@register.filter
def colour_quantity(item, colour):
    """A waybill line's quantity in one colour column; None when the line isn't sold by colour ("NA")."""
    return item.quantity_for(colour)
