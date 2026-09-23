"""Give every existing business the one store it has been trading from all along (PRD P6-F21).

Businesses predate stores, so their quotes, waybills and purchases currently hang off the business
directly. This creates the store those records will be attached to when `store` fields are added,
which is why it must run before any of them.

Idempotent: a business that already has a store is skipped.
"""

from django.db import migrations

DEFAULT_STORE_NAME = "Main"
DEFAULT_STORE_CODE = "MAIN"


def create_first_store(apps, schema_editor):
    BusinessProfile = apps.get_model("accounts", "BusinessProfile")
    Store = apps.get_model("accounts", "Store")

    have_stores = set(Store.objects.values_list("business_id", flat=True))
    Store.objects.bulk_create(
        [
            Store(
                business_id=profile.pk,
                name=DEFAULT_STORE_NAME,
                code=DEFAULT_STORE_CODE,
                address=profile.address or "",
                is_active=True,
            )
            for profile in BusinessProfile.objects.all().iterator()
            if profile.pk not in have_stores
        ]
    )


def drop_first_store(apps, schema_editor):
    """Remove only the stores this migration would have created.

    Matching on the default name and code leaves alone any branch an operator added afterwards,
    which a blanket delete would take with it.
    """
    Store = apps.get_model("accounts", "Store")
    Store.objects.filter(name=DEFAULT_STORE_NAME, code=DEFAULT_STORE_CODE).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0008_store_and_allowance")]

    operations = [migrations.RunPython(create_first_store, drop_first_store)]
