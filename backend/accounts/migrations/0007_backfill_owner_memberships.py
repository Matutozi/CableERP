"""Give every existing business's user an owner membership.

The three-step pattern: 0006 added the table, this fills it, and a later migration drops
`BusinessProfile.user` once nothing reads it. Splitting it that way means the app keeps serving
traffic between the deploys — see SYSTEM_DESIGN.md Q20.

Idempotent: it skips a business that already has a membership for that user, so re-running after a
partial failure is safe.
"""

from django.db import migrations

# The owner preset, written out rather than imported. A data migration must reproduce the state at
# the time it ran: importing ROLE_PRESETS would silently change what historical owners were granted
# every time the preset is edited, which is the retroactive-grant problem Q19 exists to prevent.
OWNER_PERMISSIONS = sorted(
    [
        "bank_details",
        "catalogue",
        "manage_members",
        "purchases",
        "quotes",
        "reports",
        "view_costs",
        "waybills",
    ]
)


def create_owner_memberships(apps, schema_editor):
    BusinessProfile = apps.get_model("accounts", "BusinessProfile")
    Membership = apps.get_model("accounts", "Membership")

    existing = set(Membership.objects.values_list("business_id", "user_id"))
    new = [
        Membership(
            business_id=profile.pk,
            user_id=profile.user_id,
            role="owner",
            permissions=list(OWNER_PERMISSIONS),
            status="active",
        )
        for profile in BusinessProfile.objects.all().iterator()
        if profile.user_id and (profile.pk, profile.user_id) not in existing
    ]
    Membership.objects.bulk_create(new)


def drop_owner_memberships(apps, schema_editor):
    """Reverse by removing only what this migration would have created.

    Deleting every membership would also take rows an operator added by hand after the upgrade.
    """
    Membership = apps.get_model("accounts", "Membership")
    Membership.objects.filter(role="owner", invited_by__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0006_membership")]

    operations = [migrations.RunPython(create_owner_memberships, drop_owner_memberships)]
