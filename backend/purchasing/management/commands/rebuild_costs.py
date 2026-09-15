"""Replay the purchase ledger over the catalogue.

The cost columns on catalogue rows are a cache. This rebuilds them from scratch, so a bug in
the write path is a thing you fix and re-run, not a thing that loses data.

    python manage.py rebuild_costs
"""

from django.core.management.base import BaseCommand

from catalogue.models import Accessory, CableSize
from purchasing import costing
from purchasing.costing import CostOutOfRange
from purchasing.models import Purchase


class Command(BaseCommand):
    help = "Recompute every catalogue row's cost from the purchase ledger."

    def handle(self, *args, **options):
        purchases = Purchase.objects.prefetch_related("items")
        skipped = []
        for purchase in purchases:
            try:
                costing.allocate_landed_cost(purchase)
            except CostOutOfRange as problem:
                # Written before the arithmetic was bounded. Name it and carry on: stopping here
                # would leave every later item without a cost because of one bad row.
                skipped.append(f"{purchase.date} {purchase.supplier_name or 'unnamed'} — {problem}")

        rows = [*CableSize.objects.select_related("cable_type"), *Accessory.objects.all()]
        for row in rows:
            costing.recalculate(row)

        costed = sum(1 for row in rows if row.last_unit_cost is not None)
        self.stdout.write(
            self.style.SUCCESS(
                f"Replayed {purchases.count()} deliveries. "
                f"{costed} of {len(rows)} catalogue items now have a cost."
            )
        )
        for problem in skipped:
            self.stdout.write(self.style.WARNING(f"Skipped: {problem}"))
