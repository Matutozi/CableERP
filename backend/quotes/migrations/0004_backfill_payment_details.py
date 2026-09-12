from django.db import migrations


def copy_payment_details(apps, schema_editor):
    """Record today's bank details on quotes written before they were snapshotted."""
    Quote = apps.get_model("quotes", "Quote")
    for quote in Quote.objects.select_related("business").iterator():
        business = quote.business
        Quote.objects.filter(pk=quote.pk).update(
            payment_bank_name=business.bank_name,
            payment_account_name=business.account_name or business.business_name,
            payment_account_number=business.account_number,
        )


class Migration(migrations.Migration):
    dependencies = [("quotes", "0003_quote_payment_account_name_and_more")]

    operations = [migrations.RunPython(copy_payment_details, migrations.RunPython.noop)]
