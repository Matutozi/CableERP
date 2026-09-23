import io
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db.utils import IntegrityError
from django.test import RequestFactory, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient, APITestCase

from catalogue.models import CableSize, CableType

from .models import (
    DEFAULT_STORE_CODE,
    OWNER_TEMPLATE_NAME,
    BusinessProfile,
    Feature,
    Invitation,
    Membership,
    RoleTemplate,
    Store,
    provision_business,
)
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


def make_member(business, user, template_name, **kwargs):
    """Create a membership from one of the business's templates.

    Seeds the defaults first so a test that only cares about membership does not have to know
    that templates exist.
    """
    RoleTemplate.seed_for(business)
    template = business.role_templates.get(name=template_name)
    return Membership.create_from_template(business, user, template, **kwargs)


class MembershipTests(APITestCase):
    """The spine: one person's access to one business (SYSTEM_DESIGN.md Q19, Q20)."""

    def setUp(self):
        self.user = User.objects.create_user("ada", password=PASSWORD)
        self.business = BusinessProfile.objects.create(user=self.user, business_name="Ada Cables")
        RoleTemplate.seed_for(self.business)

    def test_a_template_is_copied_not_referenced(self):
        """The property Q19 exists for: widening a template must not widen existing members.

        This is the whole reason permissions are stored. If access were resolved from the template
        at request time, editing "Manager" would silently re-grant every existing manager.
        """
        member = make_member(self.business, self.user, "Manager")
        self.assertNotIn(Feature.BANK_DETAILS, member.permissions)

        template = self.business.role_templates.get(name="Manager")
        template.permissions = sorted(Feature.values)
        template.save()

        member.refresh_from_db()
        self.assertFalse(member.has(Feature.BANK_DETAILS))

    def test_the_manager_preset_withholds_bank_details_and_member_management(self):
        member = make_member(self.business, self.user, "Manager")
        self.assertTrue(member.has(Feature.QUOTES))
        self.assertTrue(member.has(Feature.VIEW_COSTS))
        self.assertFalse(member.has(Feature.BANK_DETAILS))
        self.assertFalse(member.has(Feature.MANAGE_MEMBERS))

    def test_the_sales_preset_cannot_see_cost(self):
        """PRD P6-F5: cost and margin are hidden from sales everywhere."""
        member = make_member(self.business, self.user, "Sales")
        self.assertTrue(member.has(Feature.QUOTES))
        self.assertFalse(member.has(Feature.VIEW_COSTS))
        self.assertFalse(member.has(Feature.PURCHASES))

    def test_suspension_withholds_access_without_erasing_it(self):
        """PRD P6-F4: suspend without deleting, so history keeps naming them."""
        member = make_member(self.business, self.user, "Owner")
        member.status = Membership.Status.SUSPENDED
        member.save()

        self.assertFalse(member.has(Feature.QUOTES))
        self.assertIn(Feature.QUOTES, member.permissions)

    def test_a_business_can_have_two_owners(self):
        """PRD P6-F2b — impossible under the one-to-one this replaces."""
        second = User.objects.create_user("bola", password=PASSWORD)
        make_member(self.business, self.user, "Owner")
        make_member(self.business, second, "Owner")
        self.assertEqual(self.business.memberships.filter(is_owner=True).count(), 2)

    def test_one_person_cannot_hold_two_memberships_of_one_business(self):
        make_member(self.business, self.user, "Owner")
        with self.assertRaises(IntegrityError):
            make_member(self.business, self.user, "Sales")

    def test_a_user_can_belong_to_several_businesses(self):
        """PRD P6-F9."""
        other_owner = User.objects.create_user("chidi", password=PASSWORD)
        other = BusinessProfile.objects.create(user=other_owner, business_name="Chidi Cables")
        RoleTemplate.seed_for(other)
        make_member(self.business, self.user, "Owner")
        make_member(other, self.user, "Sales")
        self.assertEqual(self.user.memberships.count(), 2)

    def test_set_permissions_discards_anything_that_is_not_a_feature(self):
        member = make_member(self.business, self.user, "Sales")
        member.set_permissions([Feature.QUOTES, "not_a_feature", Feature.REPORTS])
        self.assertEqual(member.permissions, sorted([Feature.QUOTES, Feature.REPORTS]))


class TenantResolutionTests(APITestCase):
    """get_business() must not lock anyone out mid-migration (SYSTEM_DESIGN.md Q20)."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user("ada", password=PASSWORD)
        self.business = BusinessProfile.objects.create(user=self.user, business_name="Ada Cables")
        RoleTemplate.seed_for(self.business)

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
        make_member(self.business, self.user, "Owner")
        self.assertEqual(get_business(self._request()), self.business)

    def test_a_suspended_membership_does_not_resolve(self):
        member = make_member(self.business, self.user, "Owner")
        member.status = Membership.Status.SUSPENDED
        member.save()
        self.assertIsNone(get_membership(self._request()))

    def test_the_session_chooses_between_several_businesses(self):
        other_owner = User.objects.create_user("chidi", password=PASSWORD)
        other = BusinessProfile.objects.create(user=other_owner, business_name="Chidi Cables")
        RoleTemplate.seed_for(other)
        make_member(self.business, self.user, "Owner")
        make_member(other, self.user, "Sales")

        # Two memberships and no choice made: ambiguous, so neither is assumed.
        self.assertIsNone(get_membership(self._request()))

        chosen = get_membership(self._request({CURRENT_BUSINESS_SESSION_KEY: other.pk}))
        self.assertEqual(chosen.business, other)

    def test_a_stale_session_id_falls_through_instead_of_failing(self):
        make_member(self.business, self.user, "Owner")
        membership = get_membership(self._request({CURRENT_BUSINESS_SESSION_KEY: 9999}))
        self.assertEqual(membership.business, self.business)

    def test_require_allows_a_legacy_user_everything(self):
        require(self._request(), Feature.BANK_DETAILS)

    def test_require_refuses_a_feature_the_member_does_not_hold(self):
        make_member(self.business, self.user, "Sales")
        require(self._request(), Feature.QUOTES)
        with self.assertRaises(PermissionDenied):
            require(self._request(), Feature.BANK_DETAILS)


class StoreAllowanceTests(APITestCase):
    """The operator's lever, and what happens when a business exceeds it (Q21, Q22)."""

    def setUp(self):
        self.user = User.objects.create_user("ada", password=PASSWORD)
        self.business = BusinessProfile.objects.create(user=self.user, business_name="Ada Cables")
        make_member(self.business, self.user, "Owner")
        self.client.force_authenticate(self.user)

    def test_a_business_starts_with_an_allowance_of_one(self):
        self.assertEqual(self.business.store_limit, 1)

    def test_a_store_code_is_upper_cased_and_unique_per_business(self):
        Store.objects.create(business=self.business, name="Ikeja", code=" ikj ")
        self.assertEqual(self.business.stores.get(name="Ikeja").code, "IKJ")
        with self.assertRaises(IntegrityError):
            Store.objects.create(business=self.business, name="Other", code="ikj")

    def test_two_businesses_may_share_a_store_code(self):
        other_owner = User.objects.create_user("bola", password=PASSWORD)
        other = BusinessProfile.objects.create(user=other_owner, business_name="Bola Cables")
        RoleTemplate.seed_for(other)
        Store.objects.create(business=self.business, name="Ikeja", code="IKJ")
        Store.objects.create(business=other, name="Ikeja", code="IKJ")
        self.assertEqual(Store.objects.filter(code="IKJ").count(), 2)

    def test_only_active_stores_count_towards_the_allowance(self):
        Store.objects.create(business=self.business, name="Ikeja", code="IKJ")
        Store.objects.create(business=self.business, name="Closed", code="OLD", is_active=False)
        self.assertEqual(self.business.active_store_count, 1)
        self.assertFalse(self.business.is_over_store_limit)

    def test_lowering_the_allowance_below_use_puts_the_business_over_limit(self):
        """Q22: the decrease is allowed; the business is restricted until the owner chooses."""
        Store.objects.create(business=self.business, name="Ikeja", code="IKJ")
        Store.objects.create(business=self.business, name="Surulere", code="SUR")
        self.business.store_limit = 2
        self.business.save()
        self.assertFalse(self.business.is_over_store_limit)

        self.business.store_limit = 1
        self.business.save()
        self.assertTrue(self.business.is_over_store_limit)

    def test_deactivating_a_store_clears_the_over_limit_state(self):
        """The remedy must actually work, or the business is stuck restricted forever."""
        Store.objects.create(business=self.business, name="Ikeja", code="IKJ")
        surulere = Store.objects.create(business=self.business, name="Surulere", code="SUR")
        self.assertTrue(self.business.is_over_store_limit)

        surulere.is_active = False
        surulere.save()
        self.assertFalse(self.business.is_over_store_limit)

    def test_the_api_reports_the_allowance_but_refuses_to_change_it(self):
        """Q21: a limit the limited party can raise is not a limit."""
        response = self.client.get("/api/profile/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["store_limit"], 1)
        self.assertEqual(response.data["active_store_count"], 0)
        self.assertIs(response.data["is_over_store_limit"], False)

        response = self.client.patch("/api/profile/", {"store_limit": 99}, format="json")
        self.assertEqual(response.status_code, 200)
        self.business.refresh_from_db()
        self.assertEqual(self.business.store_limit, 1)


class RegistrationBuildsTheSpineTests(APITestCase):
    """Onboarding must create the membership and first store, not just the profile."""

    def test_registering_creates_an_owner_membership_and_a_first_store(self):
        response = self.client.post(
            "/api/auth/register/",
            {"business_name": "New Cables", "username": "newbie", "password": "a-strong-pass-123"},
            format="json",
            REMOTE_ADDR="198.51.100.7",
        )
        self.assertEqual(response.status_code, 201)

        business = BusinessProfile.objects.get(business_name="New Cables")
        membership = business.memberships.get()
        self.assertEqual(membership.role_label, OWNER_TEMPLATE_NAME)
        self.assertTrue(membership.is_owner)
        self.assertTrue(membership.has(Feature.BANK_DETAILS))

        store = business.stores.get()
        self.assertEqual(store.code, DEFAULT_STORE_CODE)
        self.assertTrue(store.is_active)
        self.assertFalse(business.is_over_store_limit)

    def test_a_new_business_does_not_fall_back_to_the_legacy_path(self):
        """The gap this closes: without a membership row, get_business() uses the one-to-one."""
        self.client.post(
            "/api/auth/register/",
            {"business_name": "New Cables", "username": "newbie", "password": "a-strong-pass-123"},
            format="json",
            REMOTE_ADDR="198.51.100.8",
        )
        user = User.objects.get(username="newbie")
        request = RequestFactory().get("/")
        request.user = user
        request.session = {}
        self.assertIsNotNone(get_membership(request))


class RoleTemplateTests(APITestCase):
    """Roles are the business's to define, not the platform's (SYSTEM_DESIGN.md Q26)."""

    def setUp(self):
        self.user = User.objects.create_user("ada", password=PASSWORD)
        self.business = BusinessProfile.objects.create(user=self.user, business_name="Ada Cables")
        RoleTemplate.seed_for(self.business)

    def test_a_business_starts_with_three_templates(self):
        self.assertEqual(
            sorted(self.business.role_templates.values_list("name", flat=True)),
            ["Manager", "Owner", "Sales"],
        )
        self.assertTrue(all(t.is_system for t in self.business.role_templates.all()))

    def test_seeding_twice_does_not_duplicate(self):
        RoleTemplate.seed_for(self.business)
        self.assertEqual(self.business.role_templates.count(), 3)

    def test_a_business_can_define_its_own_role(self):
        """The whole point: an org chart with a cashier is not a platform concern."""
        cashier = RoleTemplate.objects.create(business=self.business, name="Cashier")
        cashier.set_permissions([Feature.CATALOGUE, Feature.QUOTES])
        cashier.save()

        member = User.objects.create_user("emeka", password=PASSWORD)
        membership = Membership.create_from_template(self.business, member, cashier)
        self.assertEqual(membership.role_label, "Cashier")
        self.assertTrue(membership.has(Feature.QUOTES))
        self.assertFalse(membership.has(Feature.VIEW_COSTS))
        self.assertFalse(membership.is_owner)

    def test_two_businesses_may_use_the_same_role_name_differently(self):
        other_owner = User.objects.create_user("bola", password=PASSWORD)
        other = BusinessProfile.objects.create(user=other_owner, business_name="Bola Cables")
        RoleTemplate.seed_for(other)

        mine = RoleTemplate.objects.create(business=self.business, name="Cashier", permissions=[Feature.QUOTES])
        theirs = RoleTemplate.objects.create(
            business=other, name="Cashier", permissions=[Feature.QUOTES, Feature.VIEW_COSTS]
        )
        self.assertNotEqual(mine.permissions, theirs.permissions)

    def test_a_template_name_is_unique_within_a_business(self):
        with self.assertRaises(IntegrityError):
            RoleTemplate.objects.create(business=self.business, name="Manager")

    def test_the_owner_template_cannot_lose_member_management(self):
        """Otherwise one bad edit locks a business out of administering itself."""
        owner = self.business.role_templates.get(name=OWNER_TEMPLATE_NAME)
        with self.assertRaises(ValueError):
            owner.set_permissions([Feature.QUOTES])

    def test_permissions_can_be_set_per_person_regardless_of_template(self):
        """Templates are a starting point; the owner tunes individuals."""
        member = User.objects.create_user("emeka", password=PASSWORD)
        membership = make_member(self.business, member, "Sales")
        membership.set_permissions([*membership.permissions, Feature.VIEW_COSTS])
        membership.save()

        self.assertTrue(membership.has(Feature.VIEW_COSTS))
        self.assertNotIn(Feature.VIEW_COSTS, self.business.role_templates.get(name="Sales").permissions)

    def test_sales_can_read_the_catalogue_but_not_reprice_it(self):
        """The CATALOGUE split: you cannot quote without reading it (PRD P6-F6)."""
        sales = self.business.role_templates.get(name="Sales")
        self.assertIn(Feature.CATALOGUE, sales.permissions)
        self.assertNotIn(Feature.CATALOGUE_EDIT, sales.permissions)


class StoreScopeTests(APITestCase):
    """Staff see their own branches and no others (SYSTEM_DESIGN.md Q23)."""

    def setUp(self):
        self.user = User.objects.create_user("ada", password=PASSWORD)
        self.business = BusinessProfile.objects.create(user=self.user, business_name="Ada Cables")
        self.business.store_limit = 4
        self.business.save()
        RoleTemplate.seed_for(self.business)
        self.ikeja = Store.objects.create(business=self.business, name="Ikeja", code="IKJ")
        self.surulere = Store.objects.create(business=self.business, name="Surulere", code="SUR")
        self.aba = Store.objects.create(business=self.business, name="Aba", code="ABA")

    def test_an_owner_sees_every_store(self):
        membership = make_member(self.business, self.user, OWNER_TEMPLATE_NAME)
        self.assertTrue(membership.all_stores)
        self.assertEqual(membership.visible_stores().count(), 3)

    def test_an_owner_sees_a_branch_opened_after_they_joined(self):
        """Why all_stores is a flag and not an empty set."""
        membership = make_member(self.business, self.user, OWNER_TEMPLATE_NAME)
        Store.objects.create(business=self.business, name="Kano", code="KAN")
        self.assertEqual(membership.visible_stores().count(), 4)

    def test_a_manager_sees_only_the_branches_they_were_given(self):
        bola = User.objects.create_user("bola", password=PASSWORD)
        membership = make_member(self.business, bola, "Manager", stores=[self.ikeja, self.surulere])

        self.assertFalse(membership.all_stores)
        self.assertEqual(sorted(s.code for s in membership.visible_stores()), ["IKJ", "SUR"])
        self.assertTrue(membership.can_see_store(self.ikeja))
        self.assertFalse(membership.can_see_store(self.aba))

    def test_a_new_branch_is_not_visible_to_a_scoped_member(self):
        """The other half of why the flag exists."""
        bola = User.objects.create_user("bola", password=PASSWORD)
        membership = make_member(self.business, bola, "Manager", stores=[self.ikeja])
        Store.objects.create(business=self.business, name="Kano", code="KAN")
        self.assertEqual(membership.visible_stores().count(), 1)

    def test_a_deactivated_store_drops_out_of_scope(self):
        bola = User.objects.create_user("bola", password=PASSWORD)
        membership = make_member(self.business, bola, "Sales", stores=[self.ikeja, self.surulere])
        self.ikeja.is_active = False
        self.ikeja.save()
        self.assertEqual([s.code for s in membership.visible_stores()], ["SUR"])


class InvitationTests(APITestCase):
    """Onboarding staff: the access is chosen now, the person arrives later (Q25)."""

    def setUp(self):
        self.owner = User.objects.create_user("ada", password=PASSWORD)
        self.business = BusinessProfile.objects.create(user=self.owner, business_name="Ada Cables")
        self.business.store_limit = 3
        self.business.save()
        RoleTemplate.seed_for(self.business)
        make_member(self.business, self.owner, OWNER_TEMPLATE_NAME)
        self.ikeja = Store.objects.create(business=self.business, name="Ikeja", code="IKJ")
        self.aba = Store.objects.create(business=self.business, name="Aba", code="ABA")
        self.sales = self.business.role_templates.get(name="Sales")

    def test_issuing_returns_a_raw_token_that_is_not_stored(self):
        invitation, raw = Invitation.issue(self.business, self.sales, invited_by=self.owner, email="e@x.com")
        self.assertTrue(raw)
        self.assertNotEqual(invitation.token_hash, raw)
        self.assertEqual(invitation.token_hash, Invitation.hash_token(raw))
        self.assertNotIn(raw, str(Invitation.objects.values_list("token_hash", flat=True)))

    def test_an_invitation_copies_the_template_and_can_be_tuned(self):
        invitation, _ = Invitation.issue(
            self.business, self.sales, permissions=[Feature.QUOTES, Feature.VIEW_COSTS], stores=[self.ikeja]
        )
        self.assertEqual(invitation.role_label, "Sales")
        self.assertIn(Feature.VIEW_COSTS, invitation.permissions)
        self.assertEqual([s.code for s in invitation.stores.all()], ["IKJ"])

    def test_accepting_creates_the_membership_with_the_chosen_access(self):
        _, raw = Invitation.issue(
            self.business, self.sales, invited_by=self.owner, stores=[self.ikeja], email="e@x.com"
        )
        emeka = User.objects.create_user("emeka", password=PASSWORD)
        membership = Invitation.claim(raw).accept(emeka)

        self.assertEqual(membership.business, self.business)
        self.assertEqual(membership.role_label, "Sales")
        self.assertFalse(membership.all_stores)
        self.assertEqual([s.code for s in membership.visible_stores()], ["IKJ"])
        self.assertFalse(membership.can_see_store(self.aba))
        self.assertTrue(membership.has(Feature.QUOTES))
        self.assertFalse(membership.has(Feature.VIEW_COSTS))

    def test_a_token_cannot_be_used_twice(self):
        _, raw = Invitation.issue(self.business, self.sales, email="e@x.com")
        Invitation.claim(raw).accept(User.objects.create_user("emeka", password=PASSWORD))
        self.assertIsNone(Invitation.claim(raw))

    def test_an_expired_token_is_refused(self):
        invitation, raw = Invitation.issue(self.business, self.sales, validity_days=7, email="e@x.com")
        invitation.expires_at = timezone.now() - timedelta(seconds=1)
        invitation.save()
        self.assertIsNone(Invitation.claim(raw))
        self.assertEqual(invitation.status, "expired")

    def test_an_unknown_token_is_indistinguishable_from_a_used_one(self):
        """Both return None, so probing links teaches an attacker nothing."""
        self.assertIsNone(Invitation.claim("not-a-real-token"))

    def test_editing_the_template_after_inviting_does_not_change_the_invitation(self):
        _, raw = Invitation.issue(self.business, self.sales, email="e@x.com")
        self.sales.permissions = sorted(Feature.values)
        self.sales.save()

        membership = Invitation.claim(raw).accept(User.objects.create_user("emeka", password=PASSWORD))
        self.assertFalse(membership.has(Feature.BANK_DETAILS))

    def test_provisioning_a_business_is_idempotent(self):
        membership, _store = provision_business(self.business, self.owner)
        self.assertEqual(self.business.memberships.count(), 1)
        self.assertEqual(self.business.role_templates.count(), 3)
        self.assertTrue(membership.is_owner)


class FactoryPricePreferenceTests(APITestCase):
    """The catalogue toggle is the business's own, unlike the operator-set store allowance."""

    def setUp(self):
        self.user = User.objects.create_user("ada", password=PASSWORD)
        self.business = BusinessProfile.objects.create(user=self.user, business_name="Ada Cables")
        self.client.force_authenticate(self.user)

    def test_the_profile_reports_the_preference(self):
        response = self.client.get("/api/profile/")
        self.assertIs(response.data["show_factory_price"], False)

    def test_the_owner_can_turn_it_on(self):
        response = self.client.patch("/api/profile/", {"show_factory_price": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.business.refresh_from_db()
        self.assertTrue(self.business.show_factory_price)
