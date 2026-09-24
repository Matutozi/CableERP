"""Walk every API route as a restricted member and assert nothing confidential comes back.

Gating endpoints one at a time is whack-a-mole: the next endpoint someone adds will not be gated,
and no existing test will notice. This suite enumerates the URL conf instead, so a new route is
covered the day it is registered.

What counts as confidential here:

* **cost** — what the business paid. Hidden from anyone without `view_costs` (PRD P6-F5).
* **bank details** — where customers send money. Hidden from anyone without `bank_details`.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import get_resolver
from rest_framework.test import APITestCase

from catalogue.models import CableSize, CableType
from purchasing.models import Purchase, PurchaseItem
from quotes.models import Quote, QuoteLineItem, QuoteLineItemColour

from .models import AuditLog, BusinessProfile, Feature, Membership, provision_business, record

User = get_user_model()
PASSWORD = "a-strong-pass-123"  # noqa: S105

# Strings that must never reach a member who lacks the matching permission. Distinctive values, so
# a match is unambiguous rather than a coincidence of formatting.
SECRET_COST = "77777"  # noqa: S105
SECRET_ACCOUNT = "0125277464"  # noqa: S105

COST_KEYS = {
    "last_unit_cost",
    "average_unit_cost",
    "margin_percentage",
    "margin_amount",
    "cost_amount",
    "unit_cost",
    "total_cost",
    "costed_subtotal",
    "total_margin",
    "margin_coverage",
    "cost",
}


def api_routes():
    """Every registered `api/` route, with regex placeholders filled in."""
    found = []

    def walk(resolver, prefix=""):
        for pattern in resolver.url_patterns:
            if hasattr(pattern, "url_patterns"):
                walk(pattern, prefix + str(pattern.pattern))
            else:
                found.append(prefix + str(pattern.pattern))

    walk(get_resolver())
    return [r for r in found if r.startswith("api/")]


def find_keys(payload, keys):
    """Every one of `keys` appearing anywhere in a nested response body."""
    hits = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in keys:
                hits.add(key)
            hits |= find_keys(value, keys)
    elif isinstance(payload, list):
        for item in payload:
            hits |= find_keys(item, keys)
    return hits


class NoConfidentialLeakTests(APITestCase):
    """A sales member must not be able to reach cost or bank details by any route."""

    @classmethod
    def setUpTestData(cls):
        owner = User.objects.create_user("ada", password=PASSWORD)
        cls.business = BusinessProfile.objects.create(
            user=owner,
            business_name="Ada Cables",
            bank_name="Wema Bank",
            account_name="Ada Cables",
            account_number=SECRET_ACCOUNT,
        )
        provision_business(cls.business, owner)

        cable_type = CableType.objects.create(business=cls.business, name="Singles", unit="coil")
        cls.size = CableSize.objects.create(cable_type=cable_type, size_label="1.5mm", default_price=Decimal("33000"))
        CableSize.objects.filter(pk=cls.size.pk).update(
            last_unit_cost=Decimal(SECRET_COST), average_unit_cost=Decimal(SECRET_COST)
        )

        purchase = Purchase.objects.create(business=cls.business, date="2026-09-01", supplier_name="Coleman")
        PurchaseItem.objects.create(
            purchase=purchase, cable_size=cls.size, quantity=Decimal("1"), unit_cost=Decimal(SECRET_COST)
        )

        quote = Quote.objects.create(
            business=cls.business, customer_name="Musa", staff_name="Ada", reference_number="QT-1"
        )
        line = QuoteLineItem.objects.create(
            quote=quote,
            cable_size=cls.size,
            cable_type_name="Singles",
            size_label="1.5mm",
            unit="coil",
            unit_price=Decimal("40000"),
        )
        QuoteLineItemColour.objects.create(line_item=line, colour="", quantity=Decimal("2"))
        QuoteLineItem.objects.filter(pk=line.pk).update(unit_cost=Decimal(SECRET_COST))
        cls.quote = quote

        # A bank change writes the account number into its own summary.
        record(cls.business, owner, AuditLog.Action.BANK_CHANGED, f"account number — → {SECRET_ACCOUNT}")

        seller = User.objects.create_user("emeka", password=PASSWORD)
        template = cls.business.role_templates.get(name="Sales")
        cls.seller = seller
        Membership.create_from_template(cls.business, seller, template, all_stores=True)

    def setUp(self):
        self.client.force_authenticate(self.seller)

    def _reachable_responses(self):
        """GET every route a sales member can reach, with ids substituted in."""
        substitutions = {
            "(?P<pk>[^/.]+)": str(self.size.id),
        }
        for route in api_routes():
            url = "/" + route.replace("^", "").replace("$", "")
            for pattern, value in substitutions.items():
                url = url.replace(pattern, value)
            if "?P<" in url or "auth/" in url or "logo" in url:
                continue  # unresolved placeholder, or a non-JSON / auth-flow endpoint
            yield url, self.client.get(url)

    def test_no_route_returns_a_cost_key_to_a_member_without_view_costs(self):
        offenders = {}
        for url, response in self._reachable_responses():
            if response.status_code != 200:
                continue
            hits = find_keys(getattr(response, "data", None), COST_KEYS)
            if hits:
                offenders[url] = sorted(hits)
        self.assertEqual(offenders, {}, f"cost fields reachable without view_costs: {offenders}")

    def test_no_route_returns_the_cost_value_to_a_member_without_view_costs(self):
        """Belt and braces: the key could be renamed, the number cannot be disguised."""
        offenders = [
            url
            for url, response in self._reachable_responses()
            if response.status_code == 200 and SECRET_COST in response.content.decode()
        ]
        self.assertEqual(offenders, [], f"the cost value appeared at: {offenders}")

    def test_no_route_returns_the_account_number_to_a_member_without_bank_details(self):
        offenders = [
            url
            for url, response in self._reachable_responses()
            if response.status_code == 200 and SECRET_ACCOUNT in response.content.decode()
        ]
        self.assertEqual(offenders, [], f"the account number appeared at: {offenders}")

    def test_the_purchase_ledger_is_refused_outright(self):
        self.assertEqual(self.client.get("/api/purchases/").status_code, 403)

    def test_the_catalogue_is_readable_but_not_repricable(self):
        """A salesperson cannot quote without the catalogue, and must not reprice it (PRD P6-F6)."""
        self.assertEqual(self.client.get("/api/cable-types/").status_code, 200)
        refused = self.client.patch(f"/api/sizes/{self.size.id}/", {"default_price": "1.00"}, format="json")
        self.assertEqual(refused.status_code, 403)

    def test_an_owner_still_sees_everything(self):
        """The gates must not have broken the person they do not apply to."""
        self.client.force_authenticate(self.business.user)
        catalogue = self.client.get("/api/cable-types/")
        self.assertEqual(catalogue.status_code, 200)
        self.assertIn("last_unit_cost", catalogue.data[0]["sizes"][0])
        self.assertEqual(self.client.get("/api/purchases/").status_code, 200)
        self.assertIn(SECRET_ACCOUNT, self.client.get("/api/activity/").content.decode())

    def test_granting_view_costs_restores_the_figures(self):
        """Proves the gate is reading permissions, not hiding cost from everyone but owners."""
        membership = Membership.objects.get(user=self.seller)
        membership.set_permissions([*membership.permissions, Feature.VIEW_COSTS])
        membership.save()

        response = self.client.get("/api/cable-types/")
        self.assertIn("last_unit_cost", response.data[0]["sizes"][0])

    def test_the_enumeration_actually_visited_something(self):
        """A silent zero-route walk would make every test above pass for the wrong reason."""
        visited = [url for url, response in self._reachable_responses() if response.status_code == 200]
        self.assertGreaterEqual(len(visited), 4, f"only visited {visited}")


class StoreScopeLeakTests(APITestCase):
    """A member scoped to one branch must not see another branch's trade (SYSTEM_DESIGN.md Q32)."""

    @classmethod
    def setUpTestData(cls):
        owner = User.objects.create_user("ada", password=PASSWORD)
        cls.business = BusinessProfile.objects.create(user=owner, business_name="Ada Cables", store_limit=3)
        provision_business(cls.business, owner)
        cls.owner = owner

        from accounts.models import Store

        cls.ikeja = Store.objects.create(business=cls.business, name="Ikeja", code="IKJ")
        cls.aba = Store.objects.create(business=cls.business, name="Aba", code="ABA")

        def make_quote(reference, store):
            return Quote.objects.create(
                business=cls.business,
                store=store,
                customer_name=f"Customer {reference}",
                staff_name="Ada",
                reference_number=reference,
            )

        cls.ikeja_quote = make_quote("QT-IKJ", cls.ikeja)
        cls.aba_quote = make_quote("QT-ABA", cls.aba)
        cls.shared_quote = make_quote("QT-OLD", None)

        record(cls.business, owner, AuditLog.Action.QUOTE_CREATED, "Ikeja sale", store=cls.ikeja)
        record(cls.business, owner, AuditLog.Action.QUOTE_CREATED, "Aba sale", store=cls.aba)
        record(cls.business, owner, AuditLog.Action.PRICE_CHANGED, "Business-wide price change")

        # Scoped to Ikeja only, but otherwise fully trusted — so anything they cannot see is the
        # store scope doing the work, not a missing permission.
        seller = User.objects.create_user("emeka", password=PASSWORD)
        template = cls.business.role_templates.get(name="Owner")
        cls.membership = Membership.create_from_template(cls.business, seller, template, all_stores=False)
        cls.membership.stores.set([cls.ikeja])
        cls.seller = seller

    def setUp(self):
        self.client.force_authenticate(self.seller)

    def test_quotes_from_another_branch_are_invisible(self):
        references = {q["reference_number"] for q in self.client.get("/api/quotes/").data["results"]}
        self.assertIn("QT-IKJ", references)
        self.assertNotIn("QT-ABA", references)

    def test_another_branch_s_quote_is_404_not_403(self):
        """Same reasoning as tenant scoping (Q2): a 403 would confirm the record exists."""
        self.assertEqual(self.client.get(f"/api/quotes/{self.aba_quote.id}/").status_code, 404)

    def test_records_with_no_branch_stay_visible(self):
        """Anything predating stores belongs to the business, not to a branch."""
        references = {q["reference_number"] for q in self.client.get("/api/quotes/").data["results"]}
        self.assertIn("QT-OLD", references)

    def test_activity_is_scoped_to_the_branch(self):
        summaries = {entry["summary"] for entry in self.client.get("/api/activity/").data}
        self.assertIn("Ikeja sale", summaries)
        self.assertNotIn("Aba sale", summaries)
        self.assertIn("Business-wide price change", summaries, "unscoped history stays visible")

    def test_a_member_with_every_branch_sees_everything(self):
        self.membership.all_stores = True
        self.membership.save()
        references = {q["reference_number"] for q in self.client.get("/api/quotes/").data["results"]}
        self.assertEqual(references, {"QT-IKJ", "QT-ABA", "QT-OLD"})

    def test_adding_a_branch_to_a_membership_widens_what_they_see(self):
        """The multi-store case: an owner grants Aba as well, and Aba appears."""
        self.membership.stores.add(self.aba)
        references = {q["reference_number"] for q in self.client.get("/api/quotes/").data["results"]}
        self.assertEqual(references, {"QT-IKJ", "QT-ABA", "QT-OLD"})

    def test_the_owner_sees_every_branch(self):
        self.client.force_authenticate(self.owner)
        references = {q["reference_number"] for q in self.client.get("/api/quotes/").data["results"]}
        self.assertEqual(references, {"QT-IKJ", "QT-ABA", "QT-OLD"})

    def test_a_new_quote_is_filed_under_the_member_s_branch(self):
        response = self.client.post(
            "/api/quotes/",
            {
                "customer_name": "Musa",
                "staff_name": "Emeka",
                "line_items": [
                    {
                        "cable_type_name": "Singles",
                        "size_label": "1.5mm",
                        "unit": "coil",
                        "unit_price": "1000",
                        "colours": [{"colour": "", "quantity": 2}],
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Quote.objects.get(pk=response.data["id"]).store, self.ikeja)

    def test_no_route_returns_another_branch_s_reference(self):
        """The enumerating check, applied to store scope rather than to cost."""
        offenders = []
        for route in api_routes():
            url = "/" + route.replace("^", "").replace("$", "")
            if "?P<" in url or "auth/" in url or "logo" in url:
                continue
            response = self.client.get(url)
            if response.status_code == 200 and "QT-ABA" in response.content.decode():
                offenders.append(url)
        self.assertEqual(offenders, [], f"another branch's quote appeared at: {offenders}")


class StoreSelectorTests(APITestCase):
    """Choosing a branch narrows the view; it must never widen access (SYSTEM_DESIGN.md Q33)."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Store

        owner = User.objects.create_user("ada", password=PASSWORD)
        cls.business = BusinessProfile.objects.create(user=owner, business_name="Ada Cables", store_limit=3)
        provision_business(cls.business, owner)
        cls.owner = owner
        cls.ikeja = Store.objects.create(business=cls.business, name="Ikeja", code="IKJ")
        cls.aba = Store.objects.create(business=cls.business, name="Aba", code="ABA")

        for reference, store in (("QT-IKJ", cls.ikeja), ("QT-ABA", cls.aba), ("QT-OLD", None)):
            Quote.objects.create(
                business=cls.business,
                store=store,
                customer_name=f"Customer {reference}",
                staff_name="Ada",
                reference_number=reference,
            )

        # Sees Ikeja only. Used to prove the selector cannot reach past the membership.
        scoped_user = User.objects.create_user("emeka", password=PASSWORD)
        cls.scoped = Membership.create_from_template(
            cls.business, scoped_user, cls.business.role_templates.get(name="Owner"), all_stores=False
        )
        cls.scoped.stores.set([cls.ikeja])
        cls.scoped_user = scoped_user

    def _references(self):
        return {q["reference_number"] for q in self.client.get("/api/quotes/?page_size=50").data["results"]}

    def test_an_owner_sees_every_branch_by_default(self):
        self.client.force_authenticate(self.owner)
        self.assertEqual(self._references(), {"QT-IKJ", "QT-ABA", "QT-OLD"})

    def test_choosing_a_branch_narrows_the_view(self):
        self.client.force_authenticate(self.owner)
        response = self.client.put("/api/current-store/", {"store": self.ikeja.id}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["current"]["code"], "IKJ")
        self.assertEqual(self._references(), {"QT-IKJ", "QT-OLD"})

    def test_clearing_the_choice_restores_every_branch(self):
        self.client.force_authenticate(self.owner)
        self.client.put("/api/current-store/", {"store": self.ikeja.id}, format="json")
        self.client.put("/api/current-store/", {"store": None}, format="json")
        self.assertEqual(self._references(), {"QT-IKJ", "QT-ABA", "QT-OLD"})

    def test_a_branch_outside_the_membership_is_refused(self):
        """The selector is a preference layered on access, so it cannot reach past it."""
        self.client.force_authenticate(self.scoped_user)
        response = self.client.put("/api/current-store/", {"store": self.aba.id}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._references(), {"QT-IKJ", "QT-OLD"})

    def test_a_branch_from_another_business_is_refused(self):
        from accounts.models import Store

        other_owner = User.objects.create_user("bola", password=PASSWORD)
        other = BusinessProfile.objects.create(user=other_owner, business_name="Bola Cables")
        theirs = Store.objects.create(business=other, name="Theirs", code="THR")

        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.put("/api/current-store/", {"store": theirs.id}, format="json").status_code, 400)

    def test_a_stale_selection_falls_through_to_everything(self):
        """A member whose branches changed should find the app working, not broken."""
        self.client.force_authenticate(self.owner)
        session = self.client.session
        session["current_store_id"] = 999999
        session.save()
        self.assertEqual(self._references(), {"QT-IKJ", "QT-ABA", "QT-OLD"})

    def test_the_picker_is_hidden_when_there_is_nothing_to_choose(self):
        self.client.force_authenticate(self.scoped_user)
        response = self.client.get("/api/current-store/")
        self.assertIs(response.data["selectable"], False)
        self.assertEqual([s["code"] for s in response.data["available"]], ["IKJ"])

    def test_a_new_quote_is_filed_under_the_chosen_branch(self):
        self.client.force_authenticate(self.owner)
        self.client.put("/api/current-store/", {"store": self.aba.id}, format="json")
        response = self.client.post(
            "/api/quotes/",
            {
                "customer_name": "Musa",
                "staff_name": "Ada",
                "line_items": [
                    {
                        "cable_type_name": "Singles",
                        "size_label": "1.5mm",
                        "unit": "coil",
                        "unit_price": "1000",
                        "colours": [{"colour": "", "quantity": 2}],
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Quote.objects.get(pk=response.data["id"]).store, self.aba)


class RestrictedBusinessTests(APITestCase):
    """A business an operator has switched off: read-only, not locked out (Q34)."""

    @classmethod
    def setUpTestData(cls):
        owner = User.objects.create_user("ada", password=PASSWORD)
        cls.business = BusinessProfile.objects.create(user=owner, business_name="Ada Cables")
        provision_business(cls.business, owner)
        cls.owner = owner

        cable_type = CableType.objects.create(business=cls.business, name="Singles", unit="coil")
        cls.size = CableSize.objects.create(cable_type=cable_type, size_label="1.5mm", default_price=Decimal("33000"))
        cls.quote = Quote.objects.create(
            business=cls.business, customer_name="Musa", staff_name="Ada", reference_number="QT-1"
        )

    def setUp(self):
        self.client.force_authenticate(self.owner)
        self.business.status = BusinessProfile.Status.ACTIVE
        self.business.restricted_reason = ""
        self.business.save()

    def _restrict(self, reason=""):
        self.business.status = BusinessProfile.Status.RESTRICTED
        self.business.restricted_reason = reason
        self.business.save()

    def test_an_active_business_can_write(self):
        response = self.client.patch(f"/api/sizes/{self.size.id}/", {"default_price": "34000"}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_a_restricted_business_can_still_read_its_records(self):
        """Their data is theirs. Holding it hostage is both a bad look and a reason to churn."""
        self._restrict()
        self.assertEqual(self.client.get("/api/quotes/").status_code, 200)
        self.assertEqual(self.client.get("/api/cable-types/").status_code, 200)
        self.assertEqual(self.client.get("/api/profile/").status_code, 200)

    def test_a_restricted_business_can_still_download_a_pdf(self):
        self._restrict()
        self.assertEqual(self.client.get(f"/api/quotes/{self.quote.id}/pdf/").status_code, 200)

    def test_a_restricted_business_cannot_write(self):
        self._restrict()
        self.assertEqual(
            self.client.patch(f"/api/sizes/{self.size.id}/", {"default_price": "1"}, format="json").status_code,
            403,
        )
        self.assertEqual(
            self.client.post("/api/quotes/", {"customer_name": "X", "staff_name": "Y"}, format="json").status_code,
            403,
        )

    def test_the_refusal_explains_itself(self):
        self._restrict("Trial ended — contact sales to continue.")
        response = self.client.post("/api/quotes/", {}, format="json")
        self.assertIn("Trial ended", str(response.data))

    def test_there_is_a_sensible_message_when_no_reason_was_given(self):
        self._restrict()
        response = self.client.post("/api/quotes/", {}, format="json")
        self.assertIn("read-only", str(response.data).lower())

    def test_signing_in_still_works(self):
        """Locking them out of the door would mean they cannot reach their own records."""
        self._restrict()
        self.client.force_authenticate(None)
        response = self.client.post(
            "/api/auth/login/",
            {"username": "ada", "password": PASSWORD},
            format="json",
            REMOTE_ADDR="198.51.100.30",
        )
        self.assertEqual(response.status_code, 200)

    def test_lifting_the_restriction_restores_writing(self):
        self._restrict()
        self.business.status = BusinessProfile.Status.ACTIVE
        self.business.save()
        self.assertEqual(
            self.client.patch(f"/api/sizes/{self.size.id}/", {"default_price": "35000"}, format="json").status_code,
            200,
        )

    def test_the_api_cannot_lift_its_own_restriction(self):
        """The lever is the operator's; a business that could switch itself back on has no lever."""
        self._restrict()
        self.client.patch("/api/profile/", {"status": "active"}, format="json")
        self.business.refresh_from_db()
        self.assertTrue(self.business.is_restricted)

    def test_another_business_is_unaffected(self):
        self._restrict()
        other_owner = User.objects.create_user("bola", password=PASSWORD)
        other = BusinessProfile.objects.create(user=other_owner, business_name="Bola Cables")
        provision_business(other, other_owner)

        self.client.force_authenticate(other_owner)
        response = self.client.post("/api/stores/", {"name": "Main2", "code": "M2"}, format="json")
        self.assertNotEqual(response.status_code, 403)
