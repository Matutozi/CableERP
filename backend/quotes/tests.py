from datetime import timedelta
from decimal import Decimal

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.template.loader import render_to_string
from django.utils import timezone
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from accounts.models import BusinessProfile
from catalogue.models import Accessory, CableSize, CableType

from .models import Quote
from .templatetags.quote_format import naira, naira_or_dash, percent, quantity

User = get_user_model()


def make_business(username):
    user = User.objects.create_user(username, password="a-strong-pass-123")
    return user, BusinessProfile.objects.create(user=user, business_name=f"{username} Cables", bank_name="Wema Bank",
                                                account_number="0125277464", phone_numbers="0817, 0803")


def singles_line(price="33000", **colours):
    colours = colours or {"Red": 30, "Black": 25, "Yellow/Green": 14}
    return {
        "cable_type_name": "Singles",
        "size_label": "1.5mm",
        "unit": "coil",
        "unit_price": price,
        "colours": [{"colour": name.replace("_", "/"), "quantity": qty} for name, qty in colours.items()],
    }


def plain_line(size_label, price, qty, unit="coil", type_name="Other"):
    return {
        "cable_type_name": type_name,
        "size_label": size_label,
        "unit": unit,
        "unit_price": price,
        "colours": [{"colour": "", "quantity": qty}],
    }


def accessory_line(name="13A Switched Socket", price="2500", qty=10, unit="piece", **extra):
    return {
        "kind": "accessory",
        "item_name": name,
        "unit": unit,
        "unit_price": price,
        "colours": [{"colour": "", "quantity": qty}],
        **extra,
    }


class QuoteApiTests(APITestCase):
    def setUp(self):
        cache.clear()  # PDFs and throttle counters are cached
        self.user, self.business = make_business("ada")
        self.client.force_authenticate(self.user)

    def create_quote(self, **overrides):
        payload = {
            "customer_name": "Mr Abimbola",
            "staff_name": "Sunday Sobowale",
            "date": "2026-09-11",
            "line_items": [singles_line(), plain_line("RG6 Coaxial", "75000", 4)],
            **overrides,
        }
        return self.client.post("/api/quotes/", payload, format="json")

    def test_create_computes_totals_and_defaults_vat(self):
        response = self.create_quote(transport_cost="5000")
        self.assertEqual(response.status_code, 201, response.data)
        data = response.data
        self.assertEqual(data["reference_number"], "QT-20260911-001")
        self.assertEqual(data["vat_percentage"], "7.50")

        singles, coax = data["line_items"]
        self.assertEqual(singles["kind"], "cable")
        self.assertEqual(singles["total_quantity"], "69.00")
        self.assertEqual(singles["amount"], "2277000.00")
        self.assertEqual(singles["description"], "1.5mm Singles")
        self.assertEqual(coax["description"], "RG6 Coaxial")
        self.assertEqual(coax["amount"], "300000.00")

        self.assertEqual(data["subtotal"], "2577000.00")
        self.assertEqual(data["vat_amount"], "193275.00")
        self.assertEqual(data["grand_total"], "2775275.00")

    def test_reference_numbers_are_sequential_per_business_per_day(self):
        self.assertEqual(self.create_quote().data["reference_number"], "QT-20260911-001")
        self.assertEqual(self.create_quote().data["reference_number"], "QT-20260911-002")
        self.assertEqual(self.create_quote(date="2026-09-12").data["reference_number"], "QT-20260912-001")

        other_user, _ = make_business("bola")
        self.client.force_authenticate(other_user)
        self.assertEqual(self.create_quote().data["reference_number"], "QT-20260911-001")

    def test_reference_numbers_skip_past_deleted_quotes(self):
        self.create_quote()
        second = self.create_quote().data
        self.create_quote()
        self.client.delete(f"/api/quotes/{second['id']}/")
        self.assertEqual(self.create_quote().data["reference_number"], "QT-20260911-004")

    def test_explicit_zero_vat(self):
        data = self.create_quote(vat_percentage="0").data
        self.assertEqual(data["vat_amount"], "0.00")
        self.assertEqual(data["grand_total"], data["subtotal"])

    def test_coil_quantities_must_be_whole_but_metres_may_be_fractional(self):
        response = self.create_quote(line_items=[plain_line("RG6 Coaxial", "75000", "2.5")])
        self.assertEqual(response.status_code, 400)
        self.assertIn("whole numbers", str(response.data))

        response = self.create_quote(line_items=[plain_line("16mm", "57500", "12.5", unit="metre", type_name="Armoured")])
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["grand_total"], "772656.25")  # 718,750 + 7.5% VAT

    def test_rejects_empty_or_invalid_items(self):
        self.assertEqual(self.create_quote(line_items=[]).status_code, 400)
        bad_qty = singles_line(Red=0)
        self.assertEqual(self.create_quote(line_items=[bad_qty]).status_code, 400)
        duplicate = singles_line()
        duplicate["colours"].append({"colour": "red", "quantity": 1})
        self.assertEqual(self.create_quote(line_items=[duplicate]).status_code, 400)
        nameless = plain_line("4mm", "1", 1, type_name=" ")
        self.assertEqual(self.create_quote(line_items=[nameless]).status_code, 400)

    def test_accessory_line_items(self):
        socket = Accessory.objects.create(business=self.business, name="13A Switched Socket", default_price=2500)
        # Cable-only fields sent by mistake are discarded for accessory lines.
        line = accessory_line(accessory=socket.id, cable_type_name="stale", size_label="stale")
        response = self.create_quote(line_items=[singles_line(), line])
        self.assertEqual(response.status_code, 201, response.data)
        item = response.data["line_items"][1]
        self.assertEqual(item["kind"], "accessory")
        self.assertEqual(item["accessory"], socket.id)
        self.assertEqual(item["description"], "13A Switched Socket")
        self.assertEqual(item["cable_type_name"], "")
        self.assertEqual(item["amount"], "25000.00")
        self.assertEqual(response.data["subtotal"], "2302000.00")

        pdf = self.client.get(f"/api/quotes/{response.data['id']}/pdf/")
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b"%PDF"))

        self.assertIn("Piece quantities must be whole numbers", str(self.create_quote(line_items=[accessory_line(qty="1.5")]).data))
        self.assertEqual(self.create_quote(line_items=[accessory_line(name=" ")]).status_code, 400)
        self.assertEqual(self.create_quote(line_items=[accessory_line(unit="metre", qty="2.5")]).status_code, 201)
        self.assertEqual(self.create_quote(line_items=[accessory_line(unit="bucket")]).status_code, 400)

    def test_custom_cable_not_in_catalogue(self):
        line = plain_line("4mm", "45000", 2, type_name="Solar DC cable")
        item = self.create_quote(line_items=[line]).data["line_items"][0]
        self.assertEqual(item["description"], "4mm Solar DC cable")
        self.assertIsNone(item["cable_size"])

    def test_rejects_amounts_too_large_to_total(self):
        self.assertEqual(self.create_quote(line_items=[plain_line("RG6", "9999999999999.99", 1)]).status_code, 400)
        self.assertEqual(self.create_quote(line_items=[plain_line("RG6", "1000", "9999999999")]).status_code, 400)
        self.assertEqual(self.create_quote(transport_cost="9999999999999").status_code, 400)
        # Nothing was written, so the quote list still loads.
        self.assertEqual(self.client.get("/api/quotes/").status_code, 200)

    def test_payment_details_are_frozen_onto_the_quote(self):
        quote = self.create_quote().data
        self.assertEqual(quote["payment_account_number"], "0125277464")
        self.assertEqual(quote["payment_bank_name"], "Wema Bank")

        self.business.bank_name = "Some Other Bank"
        self.business.account_number = "9999999999"
        self.business.save()

        detail = self.client.get(f"/api/quotes/{quote['id']}/").data
        self.assertEqual(detail["payment_account_number"], "0125277464")
        rendered = render_to_string(
            "quotes/quote_pdf.html",
            {"quote": Quote.objects.get(pk=quote["id"]), "business": self.business},
        )
        self.assertIn("0125277464", rendered)
        self.assertNotIn("9999999999", rendered)

    def test_update_replaces_line_items_but_keeps_reference(self):
        quote = self.create_quote().data
        payload = {**quote, "customer_name": "Mrs Adeyemi", "line_items": [singles_line(price="35000", Red=10)]}
        response = self.client.put(f"/api/quotes/{quote['id']}/", payload, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["reference_number"], quote["reference_number"])
        self.assertEqual(response.data["customer_name"], "Mrs Adeyemi")
        self.assertEqual(len(response.data["line_items"]), 1)
        self.assertEqual(response.data["subtotal"], "350000.00")

    def test_quotes_are_capped_at_200_items(self):
        line = plain_line("RG6 Coaxial", "1000", 1)
        self.assertEqual(self.create_quote(line_items=[line] * 200).status_code, 201)
        too_many = self.create_quote(line_items=[line] * 201)
        self.assertEqual(too_many.status_code, 400)
        self.assertIn("up to 200 items", str(too_many.data))

    def test_pdf_is_rendered_once_per_version(self):
        quote = self.create_quote().data
        with patch("quotes.pdf.render_quote_pdf", return_value=b"%PDF-fake") as render:
            self.client.get(f"/api/quotes/{quote['id']}/pdf/")
            self.client.get(f"/api/quotes/{quote['id']}/pdf/")
            self.assertEqual(render.call_count, 1)  # second download came from cache

            self.client.patch(f"/api/quotes/{quote['id']}/", {"customer_name": "Changed"}, format="json")
            self.client.get(f"/api/quotes/{quote['id']}/pdf/")
            self.assertEqual(render.call_count, 2)  # editing the quote invalidates it

    def test_sent_quotes_are_locked_and_revised_instead(self):
        quote = self.create_quote().data
        sent = self.client.patch(f"/api/quotes/{quote['id']}/", {"status": "sent"}, format="json")
        self.assertEqual(sent.status_code, 200)
        self.assertIsNotNone(sent.data["sent_at"])

        blocked = self.client.put(f"/api/quotes/{quote['id']}/", {**quote, "customer_name": "Someone else"}, format="json")
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("Create a revision", str(blocked.data))
        self.assertEqual(self.client.patch(f"/api/quotes/{quote['id']}/", {"notes": "x"}, format="json").status_code, 400)
        self.assertEqual(self.client.delete(f"/api/quotes/{quote['id']}/").status_code, 400)

        revision = self.client.post(f"/api/quotes/{quote['id']}/revise/", format="json")
        self.assertEqual(revision.status_code, 201, revision.data)
        self.assertEqual(revision.data["status"], "draft")
        self.assertEqual(revision.data["revision_of"], quote["id"])
        self.assertEqual(revision.data["revision_of_reference"], quote["reference_number"])
        self.assertNotEqual(revision.data["reference_number"], quote["reference_number"])
        self.assertEqual(revision.data["subtotal"], quote["subtotal"])
        self.assertEqual(len(revision.data["line_items"]), len(quote["line_items"]))

        # The revision is editable, and the sent original is untouched.
        edited = self.client.put(f"/api/quotes/{revision.data['id']}/",
                                 {**revision.data, "customer_name": "Mrs Adeyemi"}, format="json")
        self.assertEqual(edited.status_code, 200)
        original = self.client.get(f"/api/quotes/{quote['id']}/").data
        self.assertEqual(original["customer_name"], "Mr Abimbola")
        self.assertEqual(original["status"], "sent")

    def test_quote_events_reach_the_change_history(self):
        quote = self.create_quote().data
        self.client.patch(f"/api/quotes/{quote['id']}/", {"status": "sent"}, format="json")
        self.client.post(f"/api/quotes/{quote['id']}/revise/", format="json")
        self.client.delete(f"/api/quotes/{quote['id']}/")  # refused: sent quotes are records

        entries = self.client.get("/api/activity/").data
        self.assertEqual([entry["action"] for entry in entries],
                         ["quote_revised", "quote_sent", "quote_created"])  # newest first, no delete line
        self.assertEqual(entries[1]["reference"], quote["reference_number"])
        self.assertIn("Mr Abimbola", entries[1]["summary"])

    def test_mark_as_sent_with_patch(self):
        quote = self.create_quote().data
        response = self.client.patch(f"/api/quotes/{quote['id']}/", {"status": "sent"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "sent")
        self.assertEqual(len(response.data["line_items"]), 2)

    def test_line_item_keeps_snapshot_when_catalogue_changes(self):
        cable_type = CableType.objects.create(business=self.business, name="Flat")
        size = CableSize.objects.create(cable_type=cable_type, size_label="1mm x 2C", default_price=66500)
        line = plain_line("1mm x 2C", "66500", 2, type_name="Flat")
        quote = self.create_quote(line_items=[{**line, "cable_size": size.id}]).data
        self.assertEqual(quote["line_items"][0]["cable_size"], size.id)

        size.delete()
        detail = self.client.get(f"/api/quotes/{quote['id']}/").data
        self.assertIsNone(detail["line_items"][0]["cable_size"])
        self.assertEqual(detail["line_items"][0]["description"], "1mm x 2C Flat")
        self.assertEqual(detail["subtotal"], "133000.00")

    def test_cannot_use_or_see_another_business_data(self):
        other_user, other = make_business("bola")
        other_type = CableType.objects.create(business=other, name="Flex")
        other_size = CableSize.objects.create(cable_type=other_type, size_label="1.5mm x 3C", default_price=1)
        other_accessory = Accessory.objects.create(business=other, name="Breaker", default_price=1)
        line = {**plain_line("1.5mm x 3C", "1", 1, type_name="Flex"), "cable_size": other_size.id}
        self.assertEqual(self.create_quote(line_items=[line]).status_code, 400)
        self.assertEqual(self.create_quote(line_items=[accessory_line(accessory=other_accessory.id)]).status_code, 400)

        mine = self.create_quote().data
        self.client.force_authenticate(other_user)
        self.assertEqual(self.client.get("/api/quotes/").data["results"], [])
        self.assertEqual(self.client.get(f"/api/quotes/{mine['id']}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/quotes/{mine['id']}/pdf/").status_code, 404)

    def test_list_is_paginated_and_searchable(self):
        self.create_quote()
        self.create_quote(customer_name="Mrs Adeyemi")

        page = self.client.get("/api/quotes/").data
        self.assertEqual(page["count"], 2)
        self.assertIsNone(page["next"])
        self.assertEqual(page["results"][1]["grand_total"], "2770275.00")

        first = self.client.get("/api/quotes/?page_size=1").data
        self.assertEqual(len(first["results"]), 1)
        self.assertIsNotNone(first["next"])

        found = self.client.get("/api/quotes/?search=adeyemi").data
        self.assertEqual([q["customer_name"] for q in found["results"]], ["Mrs Adeyemi"])
        by_reference = self.client.get("/api/quotes/?search=QT-20260911-001").data
        self.assertEqual(by_reference["count"], 1)

    def test_pdf_download(self):
        quote = self.create_quote(transport_cost="0").data
        response = self.client.get(f"/api/quotes/{quote['id']}/pdf/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn('attachment; filename="QT-20260911-001.pdf"', response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

        inline = self.client.get(f"/api/quotes/{quote['id']}/pdf/?inline=1")
        self.assertTrue(inline["Content-Disposition"].startswith("inline"))


class QuoteModelTests(APITestCase):
    def test_totals_round_half_up(self):
        _, business = make_business("ada")
        quote = Quote.objects.create(business=business, reference_number="QT-1", customer_name="A", staff_name="B",
                                     vat_percentage=Decimal("7.5"))
        item = quote.line_items.create(cable_type_name="Armoured", size_label="16mm", unit="metre", unit_price=Decimal("0.33"))
        item.colours.create(colour="", quantity=Decimal("0.5"))  # 0.165 -> 0.17
        self.assertEqual(item.amount, Decimal("0.17"))
        self.assertEqual(quote.vat_amount, Decimal("0.01"))


class FormatFilterTests(SimpleTestCase):
    def test_filters(self):
        self.assertEqual(naira(Decimal("2277000")), "2,277,000.00")
        self.assertEqual(naira_or_dash(Decimal("0.00")), "-")
        self.assertEqual(naira_or_dash(Decimal("5000")), "5,000.00")
        self.assertEqual(quantity(Decimal("69.00"), "coil"), "69 coils")
        self.assertEqual(quantity(Decimal("1.00"), "coil"), "1 coil")
        self.assertEqual(quantity(Decimal("12.50"), "metre"), "12.5 metres")
        self.assertEqual(quantity(Decimal("10"), "piece"), "10 pieces")
        self.assertEqual(quantity(Decimal("1"), "box"), "1 box")
        self.assertEqual(quantity(Decimal("1200"), ""), "1,200")
        self.assertEqual(percent(Decimal("7.50")), "7.5%")
        self.assertEqual(percent(Decimal("10.00")), "10%")


class QuoteDateTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user, self.business = make_business("ada")
        self.client.force_authenticate(self.user)

    def post(self, date):
        return self.client.post("/api/quotes/", {
            "customer_name": "Dangote", "staff_name": "Ada", "date": date.isoformat(),
            "line_items": [plain_line("1.5mm", "33000", 2)],
        }, format="json")

    def test_a_quote_cannot_be_dated_in_the_future(self):
        """The date drives the reference number, so a future one misfiles the quote as well."""
        response = self.post(timezone.localdate() + timedelta(days=1))
        self.assertEqual(response.status_code, 400)
        self.assertIn("future", str(response.data))

    def test_today_and_the_past_are_fine(self):
        self.assertEqual(self.post(timezone.localdate()).status_code, 201)
        self.assertEqual(self.post(timezone.localdate() - timedelta(days=7)).status_code, 201)


class QuoteMarginTests(APITestCase):
    """Cost is snapshotted onto a quote, frozen when it is sent, and never shown to a customer."""

    def setUp(self):
        cache.clear()
        self.user, self.business = make_business("ada")
        self.client.force_authenticate(self.user)
        cable_type = CableType.objects.create(business=self.business, name="Flex", unit="coil")
        self.size = CableSize.objects.create(cable_type=cable_type, size_label="2.5mm", default_price="90000")
        self.restock("72000")

    def restock(self, unit_cost, days_ago=30):
        response = self.client.post(
            "/api/purchases/",
            {
                "date": (timezone.localdate() - timedelta(days=days_ago)).isoformat(),
                "items": [{"cable_size": self.size.pk, "quantity": "1", "entry_unit": "coil", "unit_cost": unit_cost}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def create_quote(self, lines=None):
        lines = lines or [{
            "cable_type_name": "Flex", "size_label": "2.5mm", "unit": "coil", "unit_price": "90000",
            "cable_size": self.size.pk, "colours": [{"colour": "", "quantity": 2}],
        }]
        response = self.client.post(
            "/api/quotes/",
            {"customer_name": "Dangote", "staff_name": "Ada", "vat_percentage": "0", "line_items": lines},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def test_margin_is_computed_from_the_catalogue_cost(self):
        quote = self.create_quote()
        self.assertEqual(quote["line_items"][0]["unit_cost"], "72000.0000")
        self.assertEqual(quote["total_cost"], "144000.00")
        self.assertEqual(quote["total_margin"], "36000.00")
        self.assertEqual(quote["margin_percentage"], "20.00")

    def test_a_sent_quote_keeps_the_margin_it_was_written_with(self):
        quote = self.create_quote()
        sent = self.client.patch(f"/api/quotes/{quote['id']}/", {"status": "sent"}, format="json")
        self.assertEqual(sent.status_code, 200)
        self.assertEqual(sent.data["total_margin"], "36000.00")

        # Prices rise. The sent quote must not move.
        self.restock("85000", days_ago=0)
        again = self.client.get(f"/api/quotes/{quote['id']}/").data
        self.assertEqual(again["line_items"][0]["unit_cost"], "72000.0000")
        self.assertEqual(again["total_margin"], "36000.00")

    def test_a_draft_is_recosted_on_every_save(self):
        quote = self.create_quote()
        self.restock("85000", days_ago=0)
        updated = self.client.patch(f"/api/quotes/{quote['id']}/", {"notes": "revised pricing"}, format="json")
        self.assertEqual(updated.data["line_items"][0]["unit_cost"], "85000.0000")

    def test_a_revision_is_costed_at_todays_price(self):
        quote = self.create_quote()
        self.client.patch(f"/api/quotes/{quote['id']}/", {"status": "sent"}, format="json")
        self.restock("85000", days_ago=0)
        revision = self.client.post(f"/api/quotes/{quote['id']}/revise/", format="json")
        self.assertEqual(revision.status_code, 201)
        self.assertEqual(revision.data["line_items"][0]["unit_cost"], "85000.0000")

    def test_an_uncosted_line_is_unknown_not_free(self):
        quote = self.create_quote([
            {"cable_type_name": "Flex", "size_label": "2.5mm", "unit": "coil", "unit_price": "90000",
             "cable_size": self.size.pk, "colours": [{"colour": "", "quantity": 1}]},
            accessory_line(name="Insulation tape", price="500", qty=4),
        ])
        line = quote["line_items"][1]
        self.assertIsNone(line["unit_cost"])
        self.assertIsNone(line["margin_amount"])
        # Margin speaks only for the costed line: ₦90,000 revenue, not ₦92,000.
        self.assertEqual(quote["costed_subtotal"], "90000.00")
        self.assertEqual(quote["total_margin"], "18000.00")
        self.assertEqual(quote["margin_coverage"]["costed_items"], 1)
        self.assertEqual(quote["margin_coverage"]["total_items"], 2)
        self.assertEqual(Decimal(str(quote["margin_coverage"]["value_share"])).quantize(Decimal("0.01")),
                         Decimal("97.83"))

    def test_a_quote_with_no_costs_at_all_reports_nothing_rather_than_zero(self):
        quote = self.create_quote([accessory_line(name="Insulation tape", price="500", qty=4)])
        self.assertIsNone(quote["total_cost"])
        self.assertIsNone(quote["total_margin"])
        self.assertIsNone(quote["margin_percentage"])

    def test_cost_never_reaches_the_customer_pdf(self):
        """The one leak that would matter: a customer must never see what the stock cost."""
        quote_data = self.create_quote()
        quote = Quote.objects.get(pk=quote_data["id"])
        html = render_to_string(
            "quotes/quote_pdf.html", {"quote": quote, "business": self.business, "logo_uri": None}
        )
        for figure in ("72000", "72,000", "144,000", "36,000", "18000"):
            self.assertNotIn(figure, html, f"{figure} is cost data and must not appear on a customer's quote")

        response = self.client.get(f"/api/quotes/{quote.pk}/pdf/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"72,000", response.content)
