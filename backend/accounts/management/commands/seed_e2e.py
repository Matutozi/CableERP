"""Fixtures the browser tests need, on top of `seed_data`.

Kept out of `seed_data` deliberately: that command sets up a business someone could actually
demo, and it should not grow test users. This one creates the people and branches the e2e suites
sign in as, so a test never depends on state somebody set up by hand — which is exactly how
`permissions.mjs` and `store-scope.mjs` came to fail against a freshly seeded stack.

    python manage.py seed_e2e --password demo-pass-123

Idempotent.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import AuditLog, BusinessProfile, Membership, Store, record
from quotes.models import Quote

User = get_user_model()

SALES_USER = "seller"
BRANCH_USER = "branchstaff"


class Command(BaseCommand):
    help = "Create the members, branches and documents the browser tests expect."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="demo-pass-123")

    @transaction.atomic
    def handle(self, *args, password, **options):
        business = BusinessProfile.objects.first()
        if business is None:
            self.stderr.write("No business found — run seed_data first.")
            return

        # An account number the leak tests look for by value.
        if not business.account_number:
            business.account_number = "0125277464"
        business.bank_name = business.bank_name or "Wema Bank"
        business.store_limit = max(business.store_limit, 3)
        business.save()

        ikeja, _ = Store.objects.get_or_create(business=business, code="IKJ", defaults={"name": "Ikeja"})
        aba, _ = Store.objects.get_or_create(business=business, code="ABA", defaults={"name": "Aba"})

        for reference, store in (("QT-IKJ-1", ikeja), ("QT-ABA-1", aba), ("QT-OLD-1", None)):
            Quote.objects.get_or_create(
                business=business,
                reference_number=reference,
                defaults={"store": store, "customer_name": f"Customer {reference}", "staff_name": "Ada"},
            )

        if not business.audit_log.filter(summary="Ikeja sale happened").exists():
            record(business, business.user, AuditLog.Action.QUOTE_CREATED, "Ikeja sale happened", store=ikeja)
            record(business, business.user, AuditLog.Action.QUOTE_CREATED, "Aba sale happened", store=aba)

        # Restricted by permission, unrestricted by branch: isolates what the permission gates do.
        self._member(business, SALES_USER, password, template="Sales", all_stores=True)
        # Unrestricted by permission, restricted to one branch: isolates what the store scope does.
        branch = self._member(business, BRANCH_USER, password, template="Owner", all_stores=False)
        branch.stores.set([ikeja])

        self.stdout.write(f"e2e fixtures ready: {SALES_USER} (sales), {BRANCH_USER} (Ikeja only)")

    def _member(self, business, username, password, template, all_stores):
        user, created = User.objects.get_or_create(username=username)
        if created:
            user.set_password(password)
            user.save()
        membership = Membership.objects.filter(business=business, user=user).first()
        if membership is None:
            membership = Membership.create_from_template(
                business, user, business.role_templates.get(name=template), all_stores=all_stores
            )
        return membership
