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
