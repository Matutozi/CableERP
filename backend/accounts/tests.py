import io
import tempfile

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from PIL import Image
from rest_framework.test import APIClient, APITestCase

from catalogue.models import CableSize, CableType

from .models import BusinessProfile

User = get_user_model()
PASSWORD = "a-strong-pass-123"


class AuthTests(APITestCase):
    def setUp(self):
        cache.clear()  # throttle counters are cached; keep tests independent

    def test_register_creates_profile_and_signs_in(self):
        response = self.client.post(
            "/api/auth/register/",
            {"business_name": "Acme Cables", "full_name": "Ada Obi", "username": "ada", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["user"]["business_name"], "Acme Cables")
        self.assertEqual(response.data["user"]["full_name"], "Ada Obi")
        self.assertEqual(self.client.get("/api/profile/").data["business_name"], "Acme Cables")

    def test_register_rejects_taken_username_and_weak_password(self):
        User.objects.create_user("ada", password=PASSWORD)
        response = self.client.post(
            "/api/auth/register/", {"business_name": "X", "username": "ADA", "password": "123"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("username", response.data)

    def test_login_requires_a_csrf_token(self):
        user = User.objects.create_user("ada", password=PASSWORD)
        BusinessProfile.objects.create(user=user, business_name="Acme Cables")
        strict = APIClient(enforce_csrf_checks=True)

        blocked = strict.post("/api/auth/login/", {"username": "ada", "password": PASSWORD}, format="json")
        self.assertEqual(blocked.status_code, 403)

        strict.get("/api/auth/me/")  # plants the CSRF cookie, as the app does on load
        allowed = strict.post("/api/auth/login/", {"username": "ada", "password": PASSWORD}, format="json",
                              HTTP_X_CSRFTOKEN=strict.cookies["csrftoken"].value)
        self.assertEqual(allowed.status_code, 200)

    def test_remember_me_controls_how_long_the_session_lasts(self):
        user = User.objects.create_user("ada", password=PASSWORD)
        BusinessProfile.objects.create(user=user, business_name="Acme Cables")

        self.client.post("/api/auth/login/", {"username": "ada", "password": PASSWORD}, format="json")
        self.assertTrue(self.client.session.get_expire_at_browser_close())

        self.client.post("/api/auth/logout/")
        self.client.post("/api/auth/login/", {"username": "ada", "password": PASSWORD, "remember": True}, format="json")
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_sign_out_everywhere_drops_every_session(self):
        user = User.objects.create_user("ada", password=PASSWORD)
        BusinessProfile.objects.create(user=user, business_name="Acme Cables")
        phone, laptop = APIClient(), APIClient()
        for client in (phone, laptop):
            client.post("/api/auth/login/", {"username": "ada", "password": PASSWORD}, format="json")
        self.assertEqual(laptop.get("/api/profile/").status_code, 200)

        self.assertEqual(phone.post("/api/auth/logout-everywhere/").status_code, 204)
        self.assertEqual(laptop.get("/api/profile/").status_code, 401)
        self.assertEqual(phone.get("/api/profile/").status_code, 401)

    def test_login_me_logout(self):
        user = User.objects.create_user("ada", password=PASSWORD)
        BusinessProfile.objects.create(user=user, business_name="Acme Cables")

        self.assertIsNone(self.client.get("/api/auth/me/").data["user"])
        bad = self.client.post("/api/auth/login/", {"username": "ada", "password": "wrong"}, format="json")
        self.assertEqual(bad.status_code, 400)

        good = self.client.post("/api/auth/login/", {"username": "ada", "password": PASSWORD}, format="json")
        self.assertEqual(good.status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me/").data["user"]["username"], "ada")

        self.assertEqual(self.client.post("/api/auth/logout/").status_code, 204)
        self.assertEqual(self.client.get("/api/profile/").status_code, 401)


class ProfileTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("ada", password=PASSWORD)
        self.profile = BusinessProfile.objects.create(user=self.user, business_name="Acme Cables")
        self.client.force_authenticate(self.user)

    def test_update_profile(self):
        data = self.client.get("/api/profile/").data
        self.assertEqual(data["vat_rate"], "7.50")
        self.assertEqual(data["disclaimer"], "Prices are subject to variations in market conditions")

        data.update(bank_name="Wema Bank", account_number="0125277464", vat_rate="0", current_password=PASSWORD)
        response = self.client.put("/api/profile/", data, format="json")
        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.bank_name, "Wema Bank")
        self.assertEqual(self.profile.vat_rate, 0)

    def test_bank_details_need_the_password(self):
        data = self.client.get("/api/profile/").data
        data["bank_name"] = "Zenith Bank"

        missing = self.client.put("/api/profile/", data, format="json")
        self.assertEqual(missing.status_code, 400)
        self.assertIn("current_password", missing.data)

        wrong = self.client.put("/api/profile/", {**data, "current_password": "not-my-password"}, format="json")
        self.assertEqual(wrong.status_code, 400)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.bank_name, "")

        allowed = self.client.put("/api/profile/", {**data, "current_password": PASSWORD}, format="json")
        self.assertEqual(allowed.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.bank_name, "Zenith Bank")

    def test_other_profile_edits_do_not_need_the_password(self):
        data = self.client.get("/api/profile/").data
        data["address"] = "12 Idumota Market Road, Lagos"
        self.assertEqual(self.client.put("/api/profile/", data, format="json").status_code, 200)

    def test_upload_and_remove_logo(self):
        buffer = io.BytesIO()
        Image.new("RGB", (40, 20), "navy").save(buffer, "PNG")
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            upload = SimpleUploadedFile("logo.png", buffer.getvalue(), content_type="image/png")
            response = self.client.post("/api/profile/logo/", {"logo": upload}, format="multipart")
            self.assertEqual(response.status_code, 200)
            self.assertIn("/media/logos/", response.data["logo"])

            response = self.client.delete("/api/profile/logo/")
            self.assertIsNone(response.data["logo"])

    def test_account_without_profile_is_refused(self):
        self.client.force_authenticate(User.objects.create_user("admin", password=PASSWORD))
        self.assertEqual(self.client.get("/api/cable-types/").status_code, 403)


class ActivityTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("ada", password=PASSWORD)
        self.profile = BusinessProfile.objects.create(
            user=self.user, business_name="Acme Cables", bank_name="Wema Bank", account_number="0125277464"
        )
        self.client.force_authenticate(self.user)

    def test_price_and_bank_changes_are_recorded(self):
        cable_type = CableType.objects.create(business=self.profile, name="Singles")
        size = CableSize.objects.create(cable_type=cable_type, size_label="1.5mm", default_price=33000)
        self.client.put(f"/api/sizes/{size.id}/", {"size_label": "1.5mm", "default_price": "34000"}, format="json")

        profile = self.client.get("/api/profile/").data
        self.client.put("/api/profile/",
                        {**profile, "account_number": "9999999999", "current_password": PASSWORD}, format="json")

        entries = self.client.get("/api/activity/").data
        self.assertEqual([entry["action"] for entry in entries], ["bank_changed", "price_changed"])  # newest first
        self.assertIn("0125277464 → 9999999999", entries[0]["summary"])
        self.assertIn("₦33,000.00 → ₦34,000.00", entries[1]["summary"])
        self.assertEqual(entries[1]["reference"], "1.5mm Singles")
        self.assertEqual(entries[0]["user_name"], "ada")

    def test_saving_a_price_unchanged_records_nothing(self):
        cable_type = CableType.objects.create(business=self.profile, name="Singles")
        size = CableSize.objects.create(cable_type=cable_type, size_label="1.5mm", default_price=33000)
        self.client.put(f"/api/sizes/{size.id}/", {"size_label": "1.5mm", "default_price": "33000.00"}, format="json")
        self.assertEqual(self.client.get("/api/activity/").data, [])

    def test_history_is_per_business(self):
        cable_type = CableType.objects.create(business=self.profile, name="Singles")
        size = CableSize.objects.create(cable_type=cable_type, size_label="1.5mm", default_price=33000)
        self.client.put(f"/api/sizes/{size.id}/", {"size_label": "1.5mm", "default_price": "34000"}, format="json")

        other = User.objects.create_user("bola", password=PASSWORD)
        BusinessProfile.objects.create(user=other, business_name="Bola Cables")
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get("/api/activity/").data, [])


class ThrottleTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("ada", password=PASSWORD)
        BusinessProfile.objects.create(user=self.user, business_name="Acme Cables")

    def test_password_guessing_is_rate_limited(self):
        codes = [
            self.client.post("/api/auth/login/", {"username": "ada", "password": f"wrong{i}"}, format="json").status_code
            for i in range(11)
        ]
        self.assertEqual(codes[0], 400)
        self.assertEqual(codes[-1], 429)
        # The block covers the right password too, so guesses can't be checked against it.
        real = self.client.post("/api/auth/login/", {"username": "ada", "password": PASSWORD}, format="json")
        self.assertEqual(real.status_code, 429)


class SeedDataTests(APITestCase):
    def test_seed_is_idempotent_and_keeps_edited_prices(self):
        call_command("seed_data", password="seed-pass-123", stdout=io.StringIO())
        profile = BusinessProfile.objects.get(business_name="Acme-Oaks Ventures Limited")
        self.assertEqual(profile.cable_types.count(), 6)
        self.assertEqual(CableSize.objects.filter(cable_type__business=profile).count(), 23)
        singles = CableType.objects.get(business=profile, name="Singles")
        self.assertEqual(singles.colour_options, ["Red", "Black", "Yellow/Green"])

        size = singles.sizes.get(size_label="1.5mm")
        size.default_price = 35000
        size.save()

        call_command("seed_data", stdout=io.StringIO())
        self.assertEqual(CableSize.objects.filter(cable_type__business=profile).count(), 23)
        size.refresh_from_db()
        self.assertEqual(size.default_price, 35000)

        call_command("seed_data", reset_prices=True, stdout=io.StringIO())
        size.refresh_from_db()
        self.assertEqual(size.default_price, 33000)
