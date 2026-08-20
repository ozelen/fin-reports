from django.db import migrations, models


def mark_unparsed(apps, schema_editor):
    Receipt = apps.get_model("core", "Receipt")
    for receipt in Receipt.objects.all():
        if receipt.extracted:
            continue
        if receipt.items.exists():
            continue
        if not receipt.telegram_file_id and not receipt.file:
            continue
        receipt.needs_parse = True
        receipt.save(update_fields=["needs_parse"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_telegram_pending_upload"),
    ]

    operations = [
        migrations.AddField(
            model_name="receipt",
            name="needs_parse",
            field=models.BooleanField(
                default=False,
                help_text="Vision parse queued (rate limit or album). Bot retries until done.",
            ),
        ),
        migrations.RunPython(mark_unparsed, migrations.RunPython.noop),
    ]
