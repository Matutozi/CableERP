import secrets
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import BusinessProfile
from catalogue.models import CableSize, CableType, record_price

PROFILE = {
    "business_name": "Acme-Oaks Ventures Limited",
    "phone_numbers": "08179452969, 08033857090",
    "bank_name": "Wema Bank",
    "account_name": "Acme-Oaks Ventures Limited",
    "account_number": "0125277464",
    "disclaimer": "Prices are subject to variations in market conditions",
    "payment_terms": "100% down payment",
    "quote_validity": "24 hours from the date of this quotation",
}

# (cable type, unit, colour options, [(size, default price), ...])
CATALOGUE = [
    ("Singles", CableType.Unit.COIL, ["Red", "Black", "Yellow/Green"], [
        ("1mm", 23500), ("1.5mm", 33000), ("2.5mm", 54000), ("4mm", 87500), ("6mm", 133000),
        ("10mm", 216000), ("16mm", 338000), ("25mm", 543500), ("35mm", 743000),
    ]),
    ("Flat", CableType.Unit.COIL, [], [
        ("1mm x 2C", 66500), ("1mm x 3C", 100000), ("1.5mm x 3C", 137000), ("2.5mm x 3C", 208500),
    ]),
    ("Flex", CableType.Unit.COIL, [], [
        ("1.5mm x 3C", 187000), ("1.5mm x 4C", 244500), ("2.5mm x 3C", 280500), ("2.5mm x 4C", 371500),
        ("4mm x 3C", 420000), ("4mm x 4C", 557500), ("6mm x 4C", 802500),
    ]),
    ("Other", CableType.Unit.COIL, [], [("RG6 Coaxial", 67500), ("Cat6 Ethernet", 293500)]),
    ("Armoured", CableType.Unit.METRE, [], [("16mm", 57500)]),
    ("Retlin", CableType.Unit.METRE, [], []),
]


class Command(BaseCommand):
    help = "Create the Acme-Oaks Ventures Limited account with its business profile and cable catalogue. Safe to re-run."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="acmeoaks")
        parser.add_argument("--password", help="Password for a newly created user (default: randomly generated).")
        parser.add_argument(
            "--reset-prices",
            action="store_true",
            help="Overwrite existing size prices with the seed defaults. Without this, prices you have edited are kept.",
        )

    @transaction.atomic
    def handle(self, *args, username, password, reset_prices, **options):
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username, defaults={"first_name": "Sunday", "last_name": "Sobowale"}
        )
        if created:
            password = password or secrets.token_urlsafe(9)
            user.set_password(password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Created user {username!r} with password {password!r}"))
        else:
            self.stdout.write(f"User {username!r} already exists; password left unchanged.")

        profile, _ = BusinessProfile.objects.get_or_create(user=user, defaults=PROFILE)

        for type_order, (name, unit, colours, sizes) in enumerate(CATALOGUE):
            cable_type, _ = CableType.objects.get_or_create(
                business=profile,
                name=name,
                defaults={
                    "unit": unit,
                    "has_colour_variants": bool(colours),
                    "colour_options": colours,
                    "order": type_order,
                },
            )
            for size_order, (label, price) in enumerate(sizes):
                size, size_created = CableSize.objects.get_or_create(
                    cable_type=cable_type,
                    size_label=label,
                    defaults={"default_price": Decimal(price), "order": size_order},
                )
                if not size_created and reset_prices:
                    size.default_price = Decimal(price)
                    size.save(update_fields=["default_price"])
                # Seeding writes through the ORM, so the viewsets that normally log a price
                # point never run. Without this a fresh install has a price trend with no
                # price in it. record_price is a no-op when the price has not moved.
                record_price(size)

        self.stdout.write(self.style.SUCCESS(f"Seeded {profile.business_name}: {profile.cable_types.count()} cable types."))
