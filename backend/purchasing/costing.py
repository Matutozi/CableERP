"""Turning the purchase ledger into one cost figure per catalogue row.

Two steps, deliberately separate:

1. `allocate_landed_cost` spreads a delivery's transport across its items and normalises each
   one to the unit the item is *sold* in. This is per-delivery and never changes afterwards.
2. `recalculate` rebuilds the cached `last_unit_cost` / `average_unit_cost` on a catalogue row
   from every delivery that ever restocked it.

The cache exists only so the quote builder can read a cost without aggregating the ledger.
It is always recoverable: `manage.py rebuild_costs` replays step 1 and 2 over everything.
"""

from decimal import Decimal

from django.db import transaction

from catalogue.models import COST_DECIMAL_PLACES, MAX_PRICE, Accessory, CableSize

COST_EXPONENT = Decimal(1).scaleb(-COST_DECIMAL_PLACES)  # Decimal("0.0001")


def cost(value):
    return Decimal(value).quantize(COST_EXPONENT)


class CostOutOfRange(ValueError):
    """A delivery works out to a cost per unit that cannot be real.

    Landed cost is *derived*, so bounding the inputs is not enough: dividing a large enough
    delivery by a small enough sale quantity — usually a mistyped conversion factor — produces
    a number too big for the column it is stored in. Caught in the serializer before anything
    is written; this exception is the backstop for the paths that bypass it.
    """


def landed_unit_costs(lines, additional_cost):
    """The arithmetic of a delivery, with nothing persisted.

    `lines` is a sequence of (line_cost, sale_quantity) pairs. Returns the landed cost per sale
    unit for each line, or None where nothing measurable arrived.

    Kept separate from the rows it eventually lands on so the serializer can run the same sums
    to validate a delivery *before* saving it, rather than discovering the problem afterwards.
    """
    if not lines:
        return []

    weights = [line_cost for line_cost, _ in lines]
    if sum(weights) <= 0:
        weights = [quantity for _, quantity in lines]
    total_weight = sum(weights)

    results = []
    for (line_cost, quantity), weight in zip(lines, weights):
        share = (additional_cost * weight / total_weight) if total_weight > 0 else (additional_cost / len(lines))
        # Per-unit cost is stored rather than a line total, so a fraction of a kobo can be lost
        # here. Four decimal places keep that below a kobo on any realistic delivery.
        results.append(cost((line_cost + share) / quantity) if quantity > 0 else None)
    return results


def out_of_range(landed):
    """A landed cost above the ceiling every other price in the system obeys is a typo, not a price."""
    return landed is not None and landed > MAX_PRICE


def allocate_landed_cost(purchase):
    """Work out each item's cost per sale unit, with this delivery's transport allocated in.

    Transport is split by line value, so a ₦300,000 coil carries more of the lorry than a
    ₦2,000 roll of tape. When nothing was paid for the goods themselves (free stock, paid
    delivery) it falls back to splitting by quantity, which is the only other fair measure.
    """
    from .models import PurchaseItem

    items = list(purchase.items.all())
    if not items:
        return items

    landed = landed_unit_costs([(item.line_cost, item.sale_quantity) for item in items], purchase.additional_cost)
    for item, value in zip(items, landed):
        if out_of_range(value):
            raise CostOutOfRange(
                f"{item.item_name}: ₦{value:,.2f} per unit sold. Check the quantity and the conversion."
            )
        item.landed_unit_cost = value

    PurchaseItem.objects.bulk_update(items, ["landed_unit_cost"])
    return items


def recalculate(row):
    """Rebuild one catalogue row's cached costs from the ledger.

    `average_unit_cost` is a moving average over every delivery ever recorded. Once Phase 5
    tracks stock on hand, this should narrow to the goods still unsold — until then, an
    all-time average is the honest approximation, and `last_unit_cost` is the figure to
    price against anyway.
    """
    from .models import PurchaseItem

    field = "cable_size" if isinstance(row, CableSize) else "accessory"
    items = list(
        PurchaseItem.objects.filter(**{field: row})
        .exclude(landed_unit_cost__isnull=True)
        .select_related("purchase")
        .order_by("-purchase__date", "-purchase_id", "-id")
    )

    if not items:
        row.last_unit_cost = None
        row.average_unit_cost = None
    else:
        row.last_unit_cost = items[0].landed_unit_cost
        quantity = sum((item.sale_quantity for item in items), Decimal("0"))
        if quantity > 0:
            spend = sum((item.landed_unit_cost * item.sale_quantity for item in items), Decimal("0"))
            row.average_unit_cost = cost(spend / quantity)
        else:
            row.average_unit_cost = items[0].landed_unit_cost

    row.save(update_fields=["last_unit_cost", "average_unit_cost"])
    return row


def rows_of(purchase):
    """The catalogue rows a delivery restocked, skipping lines whose entry has been deleted."""
    return [item.catalogue_row for item in purchase.items.all() if item.catalogue_row]


def recalculate_rows(rows):
    """Rebuild the cached cost on each of `rows`, locking them in a fixed order.

    The lock matches how quote reference numbers are issued. Contention is near zero on one
    seller's account; it is there so two deliveries saved at once can't both read a stale
    average and write it back.
    """
    targets = {(type(row).__name__, row.pk) for row in rows if row is not None}
    with transaction.atomic():
        for model in (CableSize, Accessory):
            pks = sorted(pk for name, pk in targets if name == model.__name__)
            if pks:
                for row in model.objects.select_for_update().filter(pk__in=pks).order_by("pk"):
                    recalculate(row)


def refresh(purchase, also=()):
    """Apply a saved delivery: allocate its transport, then update every row it touched.

    `also` carries rows that were on the delivery *before* an edit and may no longer be,
    so removing a line still corrects the cost it used to contribute to.
    """
    with transaction.atomic():
        allocate_landed_cost(purchase)
        recalculate_rows([*rows_of(purchase), *also])
