"""Give every existing catalogue item an opening point, so the price trend starts somewhere.

Timestamped now rather than invented: we know today's price, and we do not know when it was set.
"""

from django.db import migrations


def seed(apps, schema_editor):
    PriceChange = apps.get_model("catalogue", "PriceChange")
    CableSize = apps.get_model("catalogue", "CableSize")
    Accessory = apps.get_model("catalogue", "Accessory")

    PriceChange.objects.bulk_create(
        [PriceChange(cable_size=size, price=size.default_price) for size in CableSize.objects.all()]
        + [PriceChange(accessory=item, price=item.default_price) for item in Accessory.objects.all()]
    )


def unseed(apps, schema_editor):
    apps.get_model("catalogue", "PriceChange").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("catalogue", "0005_pricechange")]
    operations = [migrations.RunPython(seed, unseed)]
