import io
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APITestCase

from accounts.models import AuditLog, BusinessProfile
from quotes.models import Quote

from .models import Waybill
from .pdf import waybill_context

User = get_user_model()


def make_business(username):
    user = User.objects.create_user(username, password="a-strong-pass-123")
    return user, BusinessProfile.objects.create(user=user, business_name=f"{username} Cables")


def png(colour="navy"):
    buffer = io.BytesIO()
    Image.new("RGB", (40, 20), colour).save(buffer, "PNG")
    return buffer.getvalue()


class WaybillFromQuoteTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user, self.business = make_business("ada")
        self.client.force_authenticate(self.user)
        response = self.client.post("/api/quotes/", {
            "customer_name": "De'Havilland Const.", "staff_name": "Ada", "vat_percentage": "0",
            "product_manufacturer": "Coleman Wires and Cables",
            "line_items": [
                {"cable_type_name": "Armoured", "size_label": "95mm x 4C", "unit": "metre", "unit_price": "57500",
                 "colours": [{"colour": "", "quantity": "3"}]},
                {"cable_type_name": "Singles", "size_label": "1.5mm", "unit": "coil", "unit_price": "33000",
                 "colours": [{"colour": "Red", "quantity": 30}, {"colour": "Black", "quantity": 25}]},
                {"kind": "accessory", "item_name": "13A socket", "unit": "piece", "unit_price": "2500",
                 "colours": [{"colour": "", "quantity": 10}]},
            ],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.quote_id = response.data["id"]
        self.quote_ref = response.data["reference_number"]

    def create(self, quote_id=None):
        return self.client.post("/api/waybills/", {"quote": quote_id or self.quote_id}, format="json")

    def test_a_quote_becomes_a_waybill_with_its_lines_and_customer(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.data)
        data = response.data
        today = timezone.localdate()
        self.assertEqual(data["reference_number"], f"WB-{today:%Y%m%d}-001")
        self.assertEqual(data["customer_name"], "De'Havilland Const.")
        self.assertEqual(data["invoice_number"], self.quote_ref, "starts as the quote's reference so they can be matched")
        self.assertEqual(data["quote_reference"], self.quote_ref)
        self.assertEqual(data["product_manufacturer"], "Coleman Wires and Cables")
        self.assertEqual([item["description"] for item in data["items"]], ["95mm x 4C", "1.5mm", "13A socket"])
        self.assertEqual([item["model_label"] for item in data["items"]], ["Armoured", "Singles", ""])
        self.assertEqual(data["colour_columns"], ["Red", "Black"])
        self.assertEqual(data["items"][1]["total_quantity"], "55.00")

    def test_quantities_are_totalled_per_unit_not_added_across_units(self):
        totals = {entry["unit"]: str(entry["quantity"]) for entry in self.create().data["totals"]}
        self.assertEqual(totals, {"metre": "3.00", "coil": "55.00", "piece": "10.00"})

    def test_a_waybill_carries_no_prices(self):
        data = self.create().data
        self.assertNotIn("unit_price", data["items"][0])
        waybill = Waybill.objects.prefetch_related("items__colours").get(pk=data["id"])
        html = render_to_string("waybills/waybill_pdf.html", waybill_context(waybill))
        for figure in ("57,500", "33,000", "2,500", "₦"):
            self.assertNotIn(figure, html)

    def test_one_quote_can_be_delivered_in_several_waybills(self):
        first, second = self.create(), self.create()
        self.assertEqual(second.status_code, 201)
        self.assertNotEqual(first.data["reference_number"], second.data["reference_number"])
        listed = self.client.get(f"/api/waybills/?quote={self.quote_id}").data
        self.assertEqual(listed["count"], 2)

    def test_a_part_delivery_reduces_quantities_and_drops_lines(self):
        data = self.create().data
        items = data["items"]
        items[1]["colours"] = [{"colour": "Red", "quantity": "10"}]  # 10 Red now, the rest later
        payload = {**data, "vehicle_number": "LSD 482 KJ", "branch": "Arepo", "items": items[:2]}
        response = self.client.put(f"/api/waybills/{data['id']}/", payload, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["vehicle_number"], "LSD 482 KJ")
        self.assertEqual(len(response.data["items"]), 2)
        self.assertEqual(response.data["items"][1]["total_quantity"], "10.00")
        self.assertEqual(response.data["colour_columns"], ["Red"])

    def test_the_quote_itself_is_untouched_by_editing_its_waybill(self):
        data = self.create().data
        items = data["items"][:1]
        self.client.put(f"/api/waybills/{data['id']}/", {**data, "items": items}, format="json")
        self.assertEqual(Quote.objects.get(pk=self.quote_id).line_items.count(), 3)

    def test_quantities_follow_the_same_rules_as_quotes(self):
        data = self.create().data
        bad = [dict(item) for item in data["items"]]
        bad[1]["colours"] = [{"colour": "Red", "quantity": "1.5"}]  # half a coil
        self.assertEqual(self.client.put(f"/api/waybills/{data['id']}/", {**data, "items": bad}, format="json").status_code, 400)
        bad[1]["colours"] = [{"colour": "Red", "quantity": "0"}]
        self.assertEqual(self.client.put(f"/api/waybills/{data['id']}/", {**data, "items": bad}, format="json").status_code, 400)
        self.assertEqual(self.client.put(f"/api/waybills/{data['id']}/", {**data, "items": []}, format="json").status_code, 400)

    def test_a_waybill_cannot_be_dated_in_the_future(self):
        data = self.create().data
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        response = self.client.put(f"/api/waybills/{data['id']}/", {**data, "date": tomorrow}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_deleting_the_quote_keeps_the_waybill(self):
        waybill_id = self.create().data["id"]
        Quote.objects.filter(pk=self.quote_id).delete()
        response = self.client.get(f"/api/waybills/{waybill_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["quote"])

    def test_waybill_numbers_are_independent_of_quote_numbers(self):
        self.assertTrue(self.quote_ref.startswith("QT-"))
        self.assertTrue(self.create().data["reference_number"].endswith("-001"))

    def test_the_pdf_downloads_under_its_reference(self):
        data = self.create().data
        response = self.client.get(f"/api/waybills/{data['id']}/pdf/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(f'{data["reference_number"]}.pdf', response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_changes_are_recorded(self):
        data = self.create().data
        self.client.put(f"/api/waybills/{data['id']}/", {**data, "branch": "Arepo"}, format="json")
        self.client.delete(f"/api/waybills/{data['id']}/")
        actions = set(AuditLog.objects.values_list("action", flat=True))
        self.assertTrue({AuditLog.Action.WAYBILL_CREATED, AuditLog.Action.WAYBILL_UPDATED,
                         AuditLog.Action.WAYBILL_DELETED} <= actions)

    def test_another_business_can_neither_convert_nor_see(self):
        waybill_id = self.create().data["id"]
        other, _ = make_business("bola")
        self.client.force_authenticate(other)
        self.assertEqual(self.create().status_code, 400)  # their quote id is not selectable
        self.assertEqual(self.client.get(f"/api/waybills/{waybill_id}/").status_code, 404)
        self.assertEqual(self.client.get("/api/waybills/").data["count"], 0)

    def test_signed_out_requests_are_refused(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/waybills/").status_code, 401)


class BrandLogoTests(APITestCase):
    """The manufacturer's logo, printed beside the distributor's on quotations and waybills."""

    def setUp(self):
        cache.clear()
        self.user, self.business = make_business("ada")
        self.client.force_authenticate(self.user)

    def test_upload_show_on_both_documents_and_remove(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            upload = SimpleUploadedFile("coleman.png", png(), content_type="image/png")
            response = self.client.post("/api/profile/brand-logo/", {"brand_logo": upload}, format="multipart")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertTrue(response.data["brand_logo"].startswith("/media/logos/"))
            self.assertIsNone(response.data["logo"], "the business's own logo is a separate image")

            quote = self.client.post("/api/quotes/", {
                "customer_name": "Dangote", "staff_name": "Ada",
                "line_items": [{"cable_type_name": "Flex", "size_label": "2.5mm", "unit": "coil",
                                "unit_price": "90000", "colours": [{"colour": "", "quantity": 1}]}],
            }, format="json").data
            self.business.refresh_from_db()
            quote_html = render_to_string("quotes/quote_pdf.html", {
                "quote": Quote.objects.get(pk=quote["id"]), "business": self.business, "logo_uri": None,
                "brand_logo_uri": "file:///brand.png",
            })
            self.assertIn('class="brand-logo"', quote_html)

            waybill = self.client.post("/api/waybills/", {"quote": quote["id"]}, format="json").data
            context = waybill_context(Waybill.objects.prefetch_related("items__colours").get(pk=waybill["id"]))
            self.assertIsNotNone(context["brand_logo_uri"])

            removed = self.client.delete("/api/profile/brand-logo/")
            self.assertIsNone(removed.data["brand_logo"])

    def test_oversized_brand_logo_is_refused(self):
        big = SimpleUploadedFile("huge.png", png() + b"0" * (2 * 1024 * 1024), content_type="image/png")
        response = self.client.post("/api/profile/brand-logo/", {"brand_logo": big}, format="multipart")
        self.assertEqual(response.status_code, 400)
