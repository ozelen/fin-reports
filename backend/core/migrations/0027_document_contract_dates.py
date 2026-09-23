from django.db import migrations, models


def backfill_contract_dates(apps, schema_editor):
    Document = apps.get_model("core", "Document")
    for doc in Document.objects.select_related("client").filter(kind="agreement"):
        fields = []
        if not doc.starts_on:
            start = doc.document_date
            if start is None and doc.client_id:
                start = doc.client.active_from
            if start:
                doc.starts_on = start
                fields.append("starts_on")
        if not doc.ends_on and doc.client_id and doc.client.active_to:
            doc.ends_on = doc.client.active_to
            fields.append("ends_on")
        if fields:
            doc.save(update_fields=fields)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0026_client_billing_match"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="starts_on",
            field=models.DateField(
                blank=True,
                help_text="Contract start date. Defaults to the signed date for agreements.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="ends_on",
            field=models.DateField(
                blank=True,
                help_text="Termination date. Empty means the contract is still open.",
                null=True,
            ),
        ),
        migrations.RunPython(backfill_contract_dates, migrations.RunPython.noop),
    ]
