import io
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db.utils import IntegrityError
from django.test import RequestFactory, override_settings
from PIL import Image
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient, APITestCase

from catalogue.models import CableSize, CableType

from .models import ROLE_PRESETS, BusinessProfile, Feature, Membership, Role
from .serializers import MAX_LOGO_BYTES, MAX_LOGO_DIMENSION
from .utils import CURRENT_BUSINESS_SESSION_KEY, get_business, get_membership, require

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
        allowed = strict.post(
            "/api/auth/login/",
            {"username": "ada", "password": PASSWORD},
            format="json",
            HTTP_X_CSRFTOKEN=strict.cookies["csrftoken"].value,
        )
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

    def test_logo_with_too_many_pixels_is_refused(self):
        """A small file can still be an enormous image; WeasyPrint decodes it in full."""
        buffer = io.BytesIO()
        # One flat colour: comfortably under the 2 MB byte cap, over the pixel cap.
        Image.new("RGB", (MAX_LOGO_DIMENSION + 200, 10), "navy").save(buffer, "PNG")
        payload = buffer.getvalue()
        self.assertLess(len(payload), MAX_LOGO_BYTES, "this fixture must pass the byte check to test the pixel one")
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            upload = SimpleUploadedFile("huge.png", payload, content_type="image/png")
            response = self.client.post("/api/profile/logo/", {"logo": upload}, format="multipart")
            self.assertEqual(response.status_code, 400)
            self.assertIn("pixels", str(response.data["logo"][0]))

    def test_logo_at_the_pixel_limit_is_accepted(self):
        buffer = io.BytesIO()
        Image.new("RGB", (MAX_LOGO_DIMENSION, 8), "navy").save(buffer, "PNG")
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            upload = SimpleUploadedFile("edge.png", buffer.getvalue(), content_type="image/png")
            response = self.client.post("/api/profile/logo/", {"logo": upload}, format="multipart")
            self.assertEqual(response.status_code, 200)

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
        self.client.put(
            "/api/profile/", {**profile, "account_number": "9999999999", "current_password": PASSWORD}, format="json"
        )

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
            self.client.post(
                "/api/auth/login/", {"username": "ada", "password": f"wrong{i}"}, format="json"
            ).status_code
            for i in range(11)
        ]
        self.assertEqual(codes[0], 400)
        self.assertEqual(codes[-1], 429)
        # The block covers the right password too, so guesses can't be checked against it.
        real = self.client.post("/api/auth/login/", {"username": "ada", "password": PASSWORD}, format="json")
        self.assertEqual(real.status_code, 429)


class LoginUsernameThrottleTests(APITestCase):
    """The per-IP limit does not stop many addresses guessing at one account."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("ada", password=PASSWORD)
        BusinessProfile.objects.create(user=self.user, business_name="Acme Cables")
        User.objects.create_user("grace", password=PASSWORD)

    def guess(self, username, address):
        return self.client.post(
            "/api/auth/login/",
            {"username": username, "password": "wrong-guess"},
            format="json",
            REMOTE_ADDR=address,
        ).status_code

    def test_one_account_cannot_be_guessed_from_many_addresses(self):
        # Every attempt comes from a different address, so the per-IP throttle never
        # fires. Only the per-username limit can stop this.
        codes = [self.guess("ada", f"203.0.113.{i}") for i in range(6)]
        self.assertEqual(codes[:5], [400] * 5)
        self.assertEqual(codes[5], 429)

    def test_the_real_password_is_blocked_too(self):
        for i in range(6):
            self.guess("ada", f"203.0.113.{i}")
        blocked = self.client.post(
            "/api/auth/login/",
            {"username": "ada", "password": PASSWORD},
            format="json",
            REMOTE_ADDR="198.51.100.7",
        )
        self.assertEqual(blocked.status_code, 429, "a correct password must not be an oracle past the limit")

    def test_throttling_one_account_does_not_block_another(self):
        for i in range(6):
            self.guess("ada", f"203.0.113.{i}")
        self.assertEqual(self.guess("grace", "198.51.100.9"), 400)

    def test_the_username_key_is_case_insensitive(self):
        # Usernames are matched case-insensitively at registration, so the throttle
        # must be too, or "ADA" would be a free extra bucket.
        for i in range(5):
            self.guess("ada", f"203.0.113.{i}")
        self.assertEqual(self.guess("ADA", "198.51.100.11"), 429)

    def test_a_request_without_a_username_is_not_thrown_away(self):
        """No username to key on: the per-IP throttle still applies, nothing errors."""
        response = self.client.post("/api/auth/login/", {"password": "x"}, format="json", REMOTE_ADDR="192.0.2.5")
        self.assertEqual(response.status_code, 400)


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


class MembershipTests(APITestCase):
    """The spine: one person's access to one business (SYSTEM_DESIGN.md Q19, Q20)."""

    def setUp(self):
        self.user = User.objects.create_user("ada", password=PASSWORD)
        self.business = BusinessProfile.objects.create(user=self.user, business_name="Ada Cables")

    def test_a_role_preset_is_copied_not_referenced(self):
        """The property Q19 exists for: widening a preset must not widen existing members.

        This is the whole reason permissions are stored. If access were resolved from the role
        name at request time, every manager on the platform would silently gain whatever a future
        release adds to the preset.
        """
        member = Membership.create_with_role(self.business, self.user, Role.MANAGER)
        self.assertNotIn(Feature.BANK_DETAILS, member.permissions)

        with patch.dict(ROLE_PRESETS, {Role.MANAGER: frozenset(Feature.values)}):
            member.refresh_from_db()
            self.assertFalse(member.has(Feature.BANK_DETAILS))

    def test_the_manager_preset_withholds_bank_details_and_member_management(self):
        member = Membership.create_with_role(self.business, self.user, Role.MANAGER)
        self.assertTrue(member.has(Feature.QUOTES))
        self.assertTrue(member.has(Feature.VIEW_COSTS))
        self.assertFalse(member.has(Feature.BANK_DETAILS))
        self.assertFalse(member.has(Feature.MANAGE_MEMBERS))

    def test_the_sales_preset_cannot_see_cost(self):
        """PRD P6-F5: cost and margin are hidden from sales everywhere."""
        member = Membership.create_with_role(self.business, self.user, Role.SALES)
        self.assertTrue(member.has(Feature.QUOTES))
        self.assertFalse(member.has(Feature.VIEW_COSTS))
        self.assertFalse(member.has(Feature.PURCHASES))

    def test_suspension_withholds_access_without_erasing_it(self):
        """PRD P6-F4: suspend without deleting, so history keeps naming them."""
        member = Membership.create_with_role(self.business, self.user, Role.OWNER)
        member.status = Membership.Status.SUSPENDED
        member.save()

        self.assertFalse(member.has(Feature.QUOTES))
        self.assertIn(Feature.QUOTES, member.permissions)

    def test_a_business_can_have_two_owners(self):
        """PRD P6-F2b — impossible under the one-to-one this replaces."""
        second = User.objects.create_user("bola", password=PASSWORD)
        Membership.create_with_role(self.business, self.user, Role.OWNER)
        Membership.create_with_role(self.business, second, Role.OWNER)
        self.assertEqual(self.business.memberships.filter(role=Role.OWNER).count(), 2)

    def test_one_person_cannot_hold_two_memberships_of_one_business(self):
        Membership.create_with_role(self.business, self.user, Role.OWNER)
        with self.assertRaises(IntegrityError):
            Membership.create_with_role(self.business, self.user, Role.SALES)

    def test_a_user_can_belong_to_several_businesses(self):
        """PRD P6-F9."""
        other_owner = User.objects.create_user("chidi", password=PASSWORD)
        other = BusinessProfile.objects.create(user=other_owner, business_name="Chidi Cables")
        Membership.create_with_role(self.business, self.user, Role.OWNER)
        Membership.create_with_role(other, self.user, Role.SALES)
        self.assertEqual(self.user.memberships.count(), 2)

    def test_set_permissions_discards_anything_that_is_not_a_feature(self):
        member = Membership.create_with_role(self.business, self.user, Role.SALES)
        member.set_permissions([Feature.QUOTES, "not_a_feature", Feature.REPORTS])
        self.assertEqual(member.permissions, sorted([Feature.QUOTES, Feature.REPORTS]))


class TenantResolutionTests(APITestCase):
    """get_business() must not lock anyone out mid-migration (SYSTEM_DESIGN.md Q20)."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user("ada", password=PASSWORD)
        self.business = BusinessProfile.objects.create(user=self.user, business_name="Ada Cables")

    def _request(self, session=None):
        request = self.factory.get("/")
        request.user = self.user
        request.session = session if session is not None else {}
        return request

    def test_a_user_with_no_membership_row_still_reaches_their_business(self):
        """The fallback. Without it, an incomplete backfill locks an owner out of their own data."""
        self.assertIsNone(get_membership(self._request()))
        self.assertEqual(get_business(self._request()), self.business)

    def test_a_membership_takes_precedence_over_the_legacy_link(self):
        Membership.create_with_role(self.business, self.user, Role.OWNER)
        self.assertEqual(get_business(self._request()), self.business)

    def test_a_suspended_membership_does_not_resolve(self):
        member = Membership.create_with_role(self.business, self.user, Role.OWNER)
        member.status = Membership.Status.SUSPENDED
        member.save()
        self.assertIsNone(get_membership(self._request()))

    def test_the_session_chooses_between_several_businesses(self):
        other_owner = User.objects.create_user("chidi", password=PASSWORD)
        other = BusinessProfile.objects.create(user=other_owner, business_name="Chidi Cables")
        Membership.create_with_role(self.business, self.user, Role.OWNER)
        Membership.create_with_role(other, self.user, Role.SALES)

        # Two memberships and no choice made: ambiguous, so neither is assumed.
        self.assertIsNone(get_membership(self._request()))

        chosen = get_membership(self._request({CURRENT_BUSINESS_SESSION_KEY: other.pk}))
        self.assertEqual(chosen.business, other)

    def test_a_stale_session_id_falls_through_instead_of_failing(self):
        Membership.create_with_role(self.business, self.user, Role.OWNER)
        membership = get_membership(self._request({CURRENT_BUSINESS_SESSION_KEY: 9999}))
        self.assertEqual(membership.business, self.business)

    def test_require_allows_a_legacy_user_everything(self):
        require(self._request(), Feature.BANK_DETAILS)

    def test_require_refuses_a_feature_the_member_does_not_hold(self):
        Membership.create_with_role(self.business, self.user, Role.SALES)
        require(self._request(), Feature.QUOTES)
        with self.assertRaises(PermissionDenied):
            require(self._request(), Feature.BANK_DETAILS)
