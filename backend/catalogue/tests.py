from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from accounts.models import BusinessProfile

from .models import Accessory, CableSize, CableType

User = get_user_model()


def make_business(username):
    user = User.objects.create_user(username, password="a-strong-pass-123")
    return user, BusinessProfile.objects.create(user=user, business_name=f"{username} Cables")


class CatalogueTests(APITestCase):
    def setUp(self):
        self.user, self.business = make_business("ada")
        self.client.force_authenticate(self.user)

    def test_create_cable_type_and_sizes(self):
        response = self.client.post(
            "/api/cable-types/",
            {"name": " Singles ", "unit": "coil", "has_colour_variants": True, "colour_options": ["Red", " Black ", "red", ""]},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["name"], "Singles")
        self.assertEqual(response.data["colour_options"], ["Red", "Black"])
        type_id = response.data["id"]

        first = self.client.post(f"/api/cable-types/{type_id}/sizes/", {"size_label": "1.5mm", "default_price": "33000"}, format="json")
        second = self.client.post(f"/api/cable-types/{type_id}/sizes/", {"size_label": "2.5mm", "default_price": "54000"}, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertLess(first.data["order"], second.data["order"])

        duplicate = self.client.post(f"/api/cable-types/{type_id}/sizes/", {"size_label": "1.5MM", "default_price": "1"}, format="json")
        self.assertEqual(duplicate.status_code, 400)

        sizes = self.client.get(f"/api/cable-types/{type_id}/sizes/").data
        self.assertEqual([s["size_label"] for s in sizes], ["1.5mm", "2.5mm"])

        response = self.client.put(f"/api/sizes/{first.data['id']}/", {"size_label": "1.5mm", "default_price": "35000.50"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["default_price"], "35000.50")

        self.assertEqual(self.client.delete(f"/api/sizes/{second.data['id']}/").status_code, 204)
        listed = self.client.get("/api/cable-types/").data
        self.assertEqual(len(listed[0]["sizes"]), 1)

    def test_colour_variants_need_colours(self):
        response = self.client.post(
            "/api/cable-types/", {"name": "Singles", "unit": "coil", "has_colour_variants": True, "colour_options": []}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("colour_options", response.data)

    def test_duplicate_type_name_rejected(self):
        CableType.objects.create(business=self.business, name="Flat")
        response = self.client.post("/api/cable-types/", {"name": "flat", "unit": "coil"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_accessories(self):
        socket = self.client.post(
            "/api/accessories/", {"name": " 13A Switched Socket ", "unit": "piece", "default_price": "2500"}, format="json"
        )
        self.assertEqual(socket.status_code, 201, socket.data)
        self.assertEqual(socket.data["name"], "13A Switched Socket")
        conduit = self.client.post(
            "/api/accessories/", {"name": "20mm Conduit Pipe", "unit": "length", "default_price": "1200"}, format="json"
        )
        self.assertLess(socket.data["order"], conduit.data["order"])

        duplicate = self.client.post("/api/accessories/", {"name": "13a switched socket", "default_price": "1"}, format="json")
        self.assertEqual(duplicate.status_code, 400)
        bad_unit = self.client.post("/api/accessories/", {"name": "Tape", "unit": "coil", "default_price": "1"}, format="json")
        self.assertEqual(bad_unit.status_code, 400)

        updated = self.client.put(
            f"/api/accessories/{socket.data['id']}/",
            {"name": "13A Switched Socket", "unit": "piece", "default_price": "2600"},
            format="json",
        )
        self.assertEqual(updated.data["default_price"], "2600.00")
        names = [entry["name"] for entry in self.client.get("/api/accessories/").data]
        self.assertEqual(names, ["13A Switched Socket", "20mm Conduit Pipe"])
        self.assertEqual(self.client.delete(f"/api/accessories/{conduit.data['id']}/").status_code, 204)
        self.assertEqual(len(self.client.get("/api/accessories/").data), 1)

    def test_prices_have_a_ceiling(self):
        cable_type = CableType.objects.create(business=self.business, name="Singles")
        too_big = self.client.post(
            f"/api/cable-types/{cable_type.id}/sizes/", {"size_label": "1.5mm", "default_price": "9999999999999"}, format="json"
        )
        self.assertEqual(too_big.status_code, 400)
        accessory = self.client.post(
            "/api/accessories/", {"name": "Gold socket", "default_price": "9999999999999"}, format="json"
        )
        self.assertEqual(accessory.status_code, 400)

    def test_other_business_catalogue_is_invisible(self):
        _, other = make_business("bola")
        other_type = CableType.objects.create(business=other, name="Flex")
        other_size = CableSize.objects.create(cable_type=other_type, size_label="1.5mm x 3C", default_price=1)
        other_accessory = Accessory.objects.create(business=other, name="Breaker", default_price=1)

        self.assertEqual(self.client.get("/api/cable-types/").data, [])
        self.assertEqual(self.client.get("/api/accessories/").data, [])
        self.assertEqual(self.client.get(f"/api/cable-types/{other_type.id}/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/cable-types/{other_type.id}/sizes/", {"size_label": "x", "default_price": 1}, format="json").status_code, 404)
        self.assertEqual(self.client.put(f"/api/sizes/{other_size.id}/", {"size_label": "x", "default_price": 1}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/cable-types/{other_type.id}/").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/accessories/{other_accessory.id}/").status_code, 404)

    def test_requires_login(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/cable-types/").status_code, 401)
        self.assertEqual(self.client.get("/api/accessories/").status_code, 401)


class PriceHistoryTests(APITestCase):
    """The trend behind each catalogue item: what it has sold for, and what it has cost."""

    def setUp(self):
        self.user, self.business = make_business("ada")
        self.client.force_authenticate(self.user)
        self.cable_type = CableType.objects.create(business=self.business, name="Flex", unit="coil")
        created = self.client.post(
            f"/api/cable-types/{self.cable_type.id}/sizes/", {"size_label": "2.5mm", "default_price": "90000"}, format="json"
        )
        self.size_id = created.data["id"]

    def history(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_a_new_size_starts_its_price_history(self):
        history = self.history(f"/api/sizes/{self.size_id}/history/")
        self.assertEqual([point["value"] for point in history["price"]], ["90000.00"])
        self.assertEqual(history["cost"], [])

    def test_every_price_change_adds_a_point(self):
        for price in ("95000", "99000"):
            self.client.put(f"/api/sizes/{self.size_id}/", {"size_label": "2.5mm", "default_price": price}, format="json")
        history = self.history(f"/api/sizes/{self.size_id}/history/")
        self.assertEqual([point["value"] for point in history["price"]], ["90000.00", "95000.00", "99000.00"])

    def test_saving_the_same_price_again_is_not_a_change(self):
        self.client.put(f"/api/sizes/{self.size_id}/", {"size_label": "2.5mm", "default_price": "90000"}, format="json")
        self.client.put(f"/api/sizes/{self.size_id}/", {"size_label": "2.5mm renamed", "default_price": "90000"}, format="json")
        self.assertEqual(len(self.history(f"/api/sizes/{self.size_id}/history/")["price"]), 1)

    def test_purchases_show_up_as_the_cost_series(self):
        for date, cost in (("2026-08-01", "70000"), ("2026-09-01", "80000")):
            response = self.client.post(
                "/api/purchases/",
                {"date": date, "items": [{"cable_size": self.size_id, "quantity": "2", "entry_unit": "coil", "unit_cost": cost}]},
                format="json",
            )
            self.assertEqual(response.status_code, 201, response.data)
        history = self.history(f"/api/sizes/{self.size_id}/history/")
        self.assertEqual([point["value"] for point in history["cost"]], ["70000.0000", "80000.0000"])
        self.assertEqual([point["date"] for point in history["cost"]], ["2026-08-01", "2026-09-01"])
        self.assertEqual(history["cost"][0]["quantity"], "2.00")

    def test_accessories_keep_a_history_too(self):
        created = self.client.post("/api/accessories/", {"name": "13A socket", "unit": "piece", "default_price": "2500"}, format="json")
        self.client.put(
            f"/api/accessories/{created.data['id']}/", {"name": "13A socket", "unit": "piece", "default_price": "2800"}, format="json"
        )
        history = self.history(f"/api/accessories/{created.data['id']}/history/")
        self.assertEqual([point["value"] for point in history["price"]], ["2500.00", "2800.00"])

    def test_another_businesss_history_is_not_reachable(self):
        other_user, _ = make_business("bola")
        self.client.force_authenticate(other_user)
        self.assertEqual(self.client.get(f"/api/sizes/{self.size_id}/history/").status_code, 404)


class PriceMovementTests(APITestCase):
    """The dashboard panel: what has been restocked lately, newest first."""

    def setUp(self):
        self.user, self.business = make_business("ada")
        self.client.force_authenticate(self.user)
        self.cable_type = CableType.objects.create(business=self.business, name="Flex", unit="coil")

    def size(self, label, price="90000"):
        return CableSize.objects.create(cable_type=self.cable_type, size_label=label, default_price=price)

    def buy(self, size, cost, date):
        response = self.client.post(
            "/api/purchases/",
            {"date": date, "items": [{"cable_size": size.pk, "quantity": "1", "entry_unit": "coil", "unit_cost": cost}]},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def movements(self):
        response = self.client.get("/api/price-movements/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_nothing_moves_until_something_is_bought(self):
        self.size("2.5mm")
        self.assertEqual(self.movements(), [])

    def test_most_recently_restocked_comes_first(self):
        old, new = self.size("2.5mm"), self.size("4mm")
        self.buy(old, "70000", "2026-08-01")
        self.buy(new, "80000", "2026-09-01")
        names = [entry["name"] for entry in self.movements()]
        self.assertEqual(names, ["4mm Flex", "2.5mm Flex"])

    def test_an_entry_carries_its_series_and_margin(self):
        size = self.size("2.5mm", price="100000")
        self.buy(size, "70000", "2026-08-01")
        self.buy(size, "80000", "2026-09-01")
        entry = self.movements()[0]
        self.assertEqual(entry["kind"], "size")
        self.assertEqual(entry["unit"], "coil")
        self.assertEqual(entry["last_unit_cost"], "80000.0000")
        self.assertEqual(entry["margin_percentage"], "20.00")
        self.assertEqual(entry["last_moved"], "2026-09-01")
        self.assertEqual([point["value"] for point in entry["history"]["cost"]], ["70000.0000", "80000.0000"])

    def test_it_shows_at_most_six_and_never_another_business(self):
        for index in range(8):
            self.buy(self.size(f"{index}mm"), "70000", f"2026-09-0{index + 1}")
        self.assertEqual(len(self.movements()), 6)

        other_user, _ = make_business("bola")
        self.client.force_authenticate(other_user)
        self.assertEqual(self.movements(), [])


class UnitChangeTests(APITestCase):
    """A recorded cost is held per sale unit, so the sale unit cannot move out from under it."""

    def setUp(self):
        self.user, self.business = make_business("ada")
        self.client.force_authenticate(self.user)
        self.cable_type = CableType.objects.create(business=self.business, name="Flex", unit="coil")
        self.size = CableSize.objects.create(cable_type=self.cable_type, size_label="2.5mm", default_price="90000")

    def put_type(self, unit):
        return self.client.put(
            f"/api/cable-types/{self.cable_type.id}/",
            {"name": "Flex", "unit": unit, "has_colour_variants": False, "colour_options": []},
            format="json",
        )

    def buy(self):
        response = self.client.post(
            "/api/purchases/",
            {"date": "2026-09-01", "items": [
                {"cable_size": self.size.pk, "quantity": "1", "entry_unit": "coil", "unit_cost": "70000"}]},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_the_unit_can_be_changed_before_anything_is_bought(self):
        self.assertEqual(self.put_type("metre").status_code, 200)

    def test_the_unit_cannot_be_changed_once_a_cost_is_recorded(self):
        self.buy()
        response = self.put_type("metre")
        self.assertEqual(response.status_code, 400)
        self.assertIn("per coil", str(response.data))
        self.assertIn("separate catalogue entry", str(response.data))
        self.cable_type.refresh_from_db()
        self.assertEqual(self.cable_type.unit, "coil", "the unit must not have moved")

    def test_other_fields_still_save_while_the_unit_stays_put(self):
        self.buy()
        response = self.client.put(
            f"/api/cable-types/{self.cable_type.id}/",
            {"name": "Flexible", "unit": "coil", "has_colour_variants": False, "colour_options": []},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["name"], "Flexible")

    def test_the_same_rule_covers_accessories(self):
        accessory = Accessory.objects.create(business=self.business, name="Tape", unit="roll", default_price="500")
        self.client.post("/api/purchases/", {"date": "2026-09-01", "items": [
            {"accessory": accessory.pk, "quantity": "10", "entry_unit": "roll", "unit_cost": "400"}]}, format="json")
        response = self.client.put(
            f"/api/accessories/{accessory.id}/", {"name": "Tape", "unit": "piece", "default_price": "500"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("per roll", str(response.data))
