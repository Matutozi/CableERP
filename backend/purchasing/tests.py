from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import AuditLog, BusinessProfile
from catalogue.models import Accessory, CableSize, CableType

from .models import Purchase, PurchaseItem

User = get_user_model()


def make_business(username):
    user = User.objects.create_user(username, password="a-strong-pass-123")
    return user, BusinessProfile.objects.create(user=user, business_name=f"{username} Cables")


class CostingTests(APITestCase):
    """The arithmetic, without the API: unit conversion, transport, and the moving average."""

    def setUp(self):
        self.user, self.business = make_business("ada")
        self.client.force_authenticate(self.user)
        # Sold by the metre, bought by the 100 m coil — the conversion that matters most here.
        self.by_metre = CableType.objects.create(business=self.business, name="Singles", unit="metre")
        self.size = CableSize.objects.create(cable_type=self.by_metre, size_label="1.5mm", default_price="1000")
        self.by_coil = CableType.objects.create(business=self.business, name="Flex", unit="coil")
        self.coil_size = CableSize.objects.create(cable_type=self.by_coil, size_label="2.5mm", default_price="90000")
        self.socket = Accessory.objects.create(business=self.business, name="13A socket", unit="piece", default_price="2500")

    def record(self, lines, additional_cost="0", date="2026-09-01"):
        payload = {"supplier_name": "Lagos Depot", "date": date, "additional_cost": additional_cost, "items": lines}
        response = self.client.post("/api/purchases/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def test_coil_cost_is_normalised_to_the_metre_it_is_sold_in(self):
        self.record([{
            "cable_size": self.size.pk, "quantity": "3", "entry_unit": "coil",
            "units_per_entry": "100", "unit_cost": "76500",
        }])
        self.size.refresh_from_db()
        # ₦76,500 a coil over 100 m is ₦765 a metre — not ₦76,500, which would show a 7,550% loss.
        self.assertEqual(self.size.last_unit_cost, Decimal("765.0000"))
        self.assertEqual(self.size.average_unit_cost, Decimal("765.0000"))

    def test_transport_is_shared_by_value_not_evenly(self):
        self.record(
            [
                {"cable_size": self.coil_size.pk, "quantity": "1", "entry_unit": "coil", "unit_cost": "90000"},
                {"accessory": self.socket.pk, "quantity": "10", "entry_unit": "piece", "unit_cost": "1000"},
            ],
            additional_cost="10000",
        )
        self.coil_size.refresh_from_db()
        self.socket.refresh_from_db()
        # Goods are ₦90,000 + ₦10,000. The coil carries 90% of the lorry, the sockets 10%.
        self.assertEqual(self.coil_size.last_unit_cost, Decimal("99000.0000"))
        self.assertEqual(self.socket.last_unit_cost, Decimal("1100.0000"))

    def test_transport_allocation_adds_up_to_what_was_paid(self):
        self.record(
            [
                {"cable_size": self.coil_size.pk, "quantity": "2", "entry_unit": "coil", "unit_cost": "90000"},
                {"accessory": self.socket.pk, "quantity": "7", "entry_unit": "piece", "unit_cost": "1000"},
            ],
            additional_cost="12345.67",
        )
        purchase = Purchase.objects.get()
        landed = sum(item.landed_unit_cost * item.sale_quantity for item in purchase.items.all())
        self.assertLess(abs(landed - purchase.total_cost), Decimal("0.01"))

    def test_average_is_weighted_by_quantity_while_last_tracks_the_newest(self):
        self.record([{"cable_size": self.coil_size.pk, "quantity": "9", "entry_unit": "coil", "unit_cost": "70000"}],
                    date="2026-08-01")
        self.record([{"cable_size": self.coil_size.pk, "quantity": "1", "entry_unit": "coil", "unit_cost": "90000"}],
                    date="2026-09-01")
        self.coil_size.refresh_from_db()
        # Replacement cost is the new price; the average still reflects the nine cheap coils.
        self.assertEqual(self.coil_size.last_unit_cost, Decimal("90000.0000"))
        self.assertEqual(self.coil_size.average_unit_cost, Decimal("72000.0000"))

    def test_margin_percentage_is_none_until_a_cost_exists(self):
        self.assertIsNone(self.coil_size.margin_percentage)
        self.record([{"cable_size": self.coil_size.pk, "quantity": "1", "entry_unit": "coil", "unit_cost": "72000"}])
        self.coil_size.refresh_from_db()
        self.assertEqual(self.coil_size.margin_percentage, Decimal("20.00"))

    def test_deleting_a_purchase_removes_the_cost_it_contributed(self):
        response = self.record([{"cable_size": self.coil_size.pk, "quantity": "1", "entry_unit": "coil", "unit_cost": "72000"}])
        self.client.delete(f"/api/purchases/{response.data['id']}/")
        self.coil_size.refresh_from_db()
        self.assertIsNone(self.coil_size.last_unit_cost)
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.Action.PURCHASE_DELETED).count(), 1)

    def test_editing_a_purchase_corrects_rows_it_no_longer_holds(self):
        response = self.record([
            {"cable_size": self.coil_size.pk, "quantity": "1", "entry_unit": "coil", "unit_cost": "72000"},
            {"accessory": self.socket.pk, "quantity": "5", "entry_unit": "piece", "unit_cost": "1800"},
        ])
        self.socket.refresh_from_db()
        self.assertIsNotNone(self.socket.last_unit_cost)

        updated = self.client.put(
            f"/api/purchases/{response.data['id']}/",
            {
                "supplier_name": "Lagos Depot",
                "date": "2026-09-01",
                "items": [{"cable_size": self.coil_size.pk, "quantity": "1", "entry_unit": "coil", "unit_cost": "72000"}],
            },
            format="json",
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        self.socket.refresh_from_db()
        self.assertIsNone(self.socket.last_unit_cost, "dropping a line should clear the cost it had set")

    def test_deleting_a_catalogue_entry_keeps_the_purchase_history(self):
        self.record([{"accessory": self.socket.pk, "quantity": "5", "entry_unit": "piece", "unit_cost": "1800"}])
        self.socket.delete()
        item = PurchaseItem.objects.get()
        self.assertIsNone(item.accessory)
        self.assertEqual(item.item_name, "13A socket")

    def test_rebuild_costs_recovers_the_cache(self):
        from django.core.management import call_command

        self.record([{"cable_size": self.coil_size.pk, "quantity": "1", "entry_unit": "coil", "unit_cost": "72000"}])
        CableSize.objects.update(last_unit_cost=None, average_unit_cost=None)
        call_command("rebuild_costs", verbosity=0)
        self.coil_size.refresh_from_db()
        self.assertEqual(self.coil_size.last_unit_cost, Decimal("72000.0000"))


class PurchaseApiTests(APITestCase):
    def setUp(self):
        self.user, self.business = make_business("ada")
        self.client.force_authenticate(self.user)
        cable_type = CableType.objects.create(business=self.business, name="Flex", unit="coil")
        self.size = CableSize.objects.create(cable_type=cable_type, size_label="2.5mm", default_price="90000")

    def post(self, items, **extra):
        return self.client.post("/api/purchases/", {"date": "2026-09-01", "items": items, **extra}, format="json")

    def test_a_line_must_point_at_a_catalogue_entry(self):
        response = self.post([{"quantity": "1", "entry_unit": "coil", "unit_cost": "72000"}])
        self.assertEqual(response.status_code, 400)

    def test_another_businesss_catalogue_is_not_reachable(self):
        _, other = make_business("bola")
        other_type = CableType.objects.create(business=other, name="Theirs", unit="coil")
        theirs = CableSize.objects.create(cable_type=other_type, size_label="4mm", default_price="1")
        response = self.post([{"cable_size": theirs.pk, "quantity": "1", "entry_unit": "coil", "unit_cost": "1"}])
        self.assertEqual(response.status_code, 400)

    def test_whole_units_only_unless_sold_by_the_metre(self):
        response = self.post([{"cable_size": self.size.pk, "quantity": "1.5", "entry_unit": "coil", "unit_cost": "72000"}])
        self.assertEqual(response.status_code, 400)
        self.assertIn("whole numbers", str(response.data))

    def test_conversion_must_be_one_when_bought_and_sold_alike(self):
        response = self.post([{
            "cable_size": self.size.pk, "quantity": "1", "entry_unit": "coil",
            "units_per_entry": "100", "unit_cost": "72000",
        }])
        self.assertEqual(response.status_code, 400)

    def test_how_an_item_is_bought_is_remembered_for_next_time(self):
        metre_type = CableType.objects.create(business=self.business, name="Singles", unit="metre")
        size = CableSize.objects.create(cable_type=metre_type, size_label="1.5mm", default_price="1000")
        self.post([{
            "cable_size": size.pk, "quantity": "2", "entry_unit": "coil",
            "units_per_entry": "100", "unit_cost": "76500",
        }])
        size.refresh_from_db()
        self.assertEqual(size.purchase_unit, "coil")
        self.assertEqual(size.units_per_purchase, Decimal("100.00"))

        # The next delivery of the same item needs neither field.
        self.post([{"cable_size": size.pk, "quantity": "1", "unit_cost": "80000"}])
        size.refresh_from_db()
        self.assertEqual(size.last_unit_cost, Decimal("800.0000"))

    def test_purchases_are_scoped_to_the_signed_in_business(self):
        self.post([{"cable_size": self.size.pk, "quantity": "1", "entry_unit": "coil", "unit_cost": "72000"}])
        other_user, _ = make_business("bola")
        self.client.force_authenticate(other_user)
        self.assertEqual(self.client.get("/api/purchases/").data["count"], 0)

    def test_signed_out_requests_are_refused(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/purchases/").status_code, 401)

    def test_the_catalogue_reports_cost_and_margin(self):
        self.post([{"cable_size": self.size.pk, "quantity": "1", "entry_unit": "coil", "unit_cost": "72000"}])
        size = self.client.get("/api/cable-types/").data[0]["sizes"][0]
        self.assertEqual(size["last_unit_cost"], "72000.0000")
        self.assertEqual(size["margin_percentage"], "20.00")


class CostBoundsTests(APITestCase):
    """Landed cost is derived, so bounding the inputs is not enough — the result is checked too."""

    def setUp(self):
        self.user, self.business = make_business("ada")
        self.client.force_authenticate(self.user)
        # Sold per coil, so a delivery may be entered in metres and fractional quantities allowed.
        cable_type = CableType.objects.create(business=self.business, name="Flex", unit="coil")
        self.size = CableSize.objects.create(cable_type=cable_type, size_label="2.5mm", default_price="90000")

    def post(self, **payload):
        return self.client.post("/api/purchases/", {"date": "2026-09-01", **payload}, format="json")

    def test_an_impossible_landed_cost_is_refused_not_stored(self):
        response = self.post(
            additional_cost="1000000000",
            items=[{"cable_size": self.size.pk, "quantity": "0.01", "entry_unit": "metre",
                    "units_per_entry": "0.01", "unit_cost": "1000000000"}],
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("per unit sold", str(response.data))
        # Nothing may survive the rejection: the bug this guards against wrote the row and then
        # failed on every subsequent read of it.
        self.assertEqual(Purchase.objects.count(), 0)
        self.size.refresh_from_db()
        self.assertIsNone(self.size.last_unit_cost)

    def test_the_message_names_the_item_and_what_to_check(self):
        response = self.post(
            items=[{"cable_size": self.size.pk, "quantity": "1", "entry_unit": "metre",
                    "units_per_entry": "0.01", "unit_cost": "1000000000"}],
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("2.5mm Flex", str(response.data))
        self.assertIn("metre", str(response.data))

    def test_an_ordinary_delivery_is_unaffected(self):
        response = self.post(
            additional_cost="15000",
            items=[{"cable_size": self.size.pk, "quantity": "3", "entry_unit": "coil", "unit_cost": "70000"}],
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.size.refresh_from_db()
        self.assertEqual(self.size.last_unit_cost, Decimal("75000.0000"))


class PurchaseDateTests(APITestCase):
    """Replacement cost is chosen by date, so a date that cannot be real must not be accepted."""

    def setUp(self):
        self.user, self.business = make_business("ada")
        self.client.force_authenticate(self.user)
        cable_type = CableType.objects.create(business=self.business, name="Flex", unit="coil")
        self.size = CableSize.objects.create(cable_type=cable_type, size_label="2.5mm", default_price="100000")

    def buy(self, date, cost):
        return self.client.post("/api/purchases/", {"date": date.isoformat(), "items": [
            {"cable_size": self.size.pk, "quantity": "1", "entry_unit": "coil", "unit_cost": cost}]}, format="json")

    def test_a_delivery_cannot_be_dated_in_the_future(self):
        response = self.buy(timezone.localdate() + timedelta(days=1), "9999")
        self.assertEqual(response.status_code, 400)
        self.assertIn("future", str(response.data))

    def test_a_mistyped_year_can_no_longer_set_the_replacement_cost(self):
        self.assertEqual(self.buy(timezone.localdate() - timedelta(days=30), "70000").status_code, 201)
        self.assertEqual(self.buy(timezone.localdate().replace(year=2099), "9999").status_code, 400)
        self.size.refresh_from_db()
        self.assertEqual(self.size.last_unit_cost, Decimal("70000.0000"))
        self.assertEqual(self.size.margin_percentage, Decimal("30.00"))

    def test_today_is_fine(self):
        self.assertEqual(self.buy(timezone.localdate(), "70000").status_code, 201)


class LongNameTests(APITestCase):
    """A cable's recorded name is size_label + type name, which together can outrun a short column."""

    def test_the_longest_name_the_catalogue_can_make_is_stored_whole(self):
        user, business = make_business("ada")
        self.client.force_authenticate(user)
        cable_type = CableType.objects.create(business=business, name="T" * 100, unit="coil")
        size = CableSize.objects.create(cable_type=cable_type, size_label="S" * 100, default_price="1000")

        response = self.client.post("/api/purchases/", {"date": "2026-09-01", "items": [
            {"cable_size": size.pk, "quantity": "1", "entry_unit": "coil", "unit_cost": "1000"}]}, format="json")
        self.assertEqual(response.status_code, 201, response.data)

        stored = PurchaseItem.objects.get()
        self.assertEqual(stored.item_name, str(size))
        self.assertEqual(len(stored.item_name), 201)
        self.assertLessEqual(len(stored.item_name), PurchaseItem._meta.get_field("item_name").max_length)
