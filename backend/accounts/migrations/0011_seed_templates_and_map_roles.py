"""Move every business onto per-business role templates, and split the catalogue permission.

Runs between 0010 (which adds the new columns) and 0012 (which drops `Membership.role`), because
it is the only migration that needs to read the old role to decide what the new one should be.

Three things happen here, all additive — **no member loses a permission**:

1. Each business gets the three default templates.
2. Each membership is pointed at the template matching its old role, with `role_label`, `is_owner`
   and `all_stores` filled in from it.
3. `catalogue` is split into `catalogue` (read) and `catalogue_edit` (write). Anyone who held the
   old combined permission gets both, so nobody's access narrows on upgrade. The sales preset gains
   read access it did not have before, which it needs in order to quote at all.
"""

from django.db import migrations

# Written out rather than imported: a data migration must reproduce the state at the time it ran,
# not follow later edits to the constants (the Q19 property applied to migrations themselves).
ALL_FEATURES = sorted(
    [
        "bank_details",
        "catalogue",
        "catalogue_edit",
        "manage_members",
        "purchases",
        "quotes",
        "reports",
        "view_costs",
        "waybills",
    ]
)
TEMPLATES = {
    "Owner": ALL_FEATURES,
    "Manager": sorted(set(ALL_FEATURES) - {"bank_details", "manage_members"}),
    "Sales": sorted(["catalogue", "quotes", "waybills"]),
}
ROLE_TO_TEMPLATE = {"owner": "Owner", "manager": "Manager", "sales": "Sales"}


def migrate_roles(apps, schema_editor):
    BusinessProfile = apps.get_model("accounts", "BusinessProfile")
    RoleTemplate = apps.get_model("accounts", "RoleTemplate")
    Membership = apps.get_model("accounts", "Membership")

    for business in BusinessProfile.objects.all().iterator():
        existing = set(business.role_templates.values_list("name", flat=True))
        RoleTemplate.objects.bulk_create(
            [
                RoleTemplate(business=business, name=name, permissions=list(perms), is_system=True)
                for name, perms in TEMPLATES.items()
                if name not in existing
            ]
        )
        by_name = {t.name: t for t in business.role_templates.all()}

        for membership in business.memberships.all():
            template_name = ROLE_TO_TEMPLATE.get(membership.role, "Sales")
            template = by_name[template_name]
            permissions = set(membership.permissions or [])
            # Everyone who could reach the catalogue keeps reading it, and gains the edit right
            # they effectively already had under the combined flag.
            if "catalogue" in permissions:
                permissions.add("catalogue_edit")
            membership.role_template = template
            membership.role_label = template_name
            membership.is_owner = template_name == "Owner"
            # Owners see branches opened later; nobody else is silently widened.
            membership.all_stores = membership.is_owner
            membership.permissions = sorted(permissions)
            membership.save(
                update_fields=["role_template", "role_label", "is_owner", "all_stores", "permissions"]
            )


def unmap_roles(apps, schema_editor):
    """Put the old role string back and drop the templates this migration created."""
    RoleTemplate = apps.get_model("accounts", "RoleTemplate")
    Membership = apps.get_model("accounts", "Membership")

    for membership in Membership.objects.all().iterator():
        membership.role = {"Owner": "owner", "Manager": "manager"}.get(membership.role_label, "sales")
        permissions = set(membership.permissions or [])
        permissions.discard("catalogue_edit")
        membership.permissions = sorted(permissions)
        membership.save(update_fields=["role", "permissions"])

    RoleTemplate.objects.filter(is_system=True).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0010_role_templates_and_invitations")]

    operations = [migrations.RunPython(migrate_roles, unmap_roles)]
