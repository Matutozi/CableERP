"""Grant the new `discount` permission to everyone who can already quote.

Until now nothing stopped a member pricing a quote line however they liked, so every person who can
write a quote can discount today. Enforcing the new permission without this migration would start
refusing quotes that worked yesterday, from people nobody decided to restrict.

Additive on purpose: **nobody loses anything here.** An owner who wants their cashiers held to the
catalogue price revokes it deliberately, on the staff screen, and that is a decision with a person's
name on it rather than a side effect of an upgrade.

The role templates are updated too, so a business's *existing* "Sales" preset keeps behaving as it
did. New businesses get the tighter default from SYSTEM_ROLE_TEMPLATES, where Sales has no discount.
"""

from django.db import migrations

QUOTES = "quotes"
DISCOUNT = "discount"


def grant_discount(apps, schema_editor):
    Membership = apps.get_model("accounts", "Membership")
    RoleTemplate = apps.get_model("accounts", "RoleTemplate")

    for model in (Membership, RoleTemplate):
        for row in model.objects.all().iterator():
            permissions = set(row.permissions or [])
            if QUOTES in permissions and DISCOUNT not in permissions:
                row.permissions = sorted(permissions | {DISCOUNT})
                row.save(update_fields=["permissions"])


def revoke_discount(apps, schema_editor):
    Membership = apps.get_model("accounts", "Membership")
    RoleTemplate = apps.get_model("accounts", "RoleTemplate")

    for model in (Membership, RoleTemplate):
        for row in model.objects.all().iterator():
            permissions = set(row.permissions or [])
            if DISCOUNT in permissions:
                row.permissions = sorted(permissions - {DISCOUNT})
                row.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0017_discount_permission")]

    operations = [migrations.RunPython(grant_discount, revoke_discount)]
