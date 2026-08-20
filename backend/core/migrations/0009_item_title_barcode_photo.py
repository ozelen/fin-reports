import django.db.models.deletion
from django.db import migrations, models


def backfill_item_transactions(apps, schema_editor):
    PurchaseItem = apps.get_model("core", "PurchaseItem")
    for item in PurchaseItem.objects.filter(
        transaction_id__isnull=True, receipt__transaction_id__isnull=False
    ).iterator():
        PurchaseItem.objects.filter(pk=item.pk).update(
            transaction_id=item.receipt.transaction_id
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_purchaseitem"),
    ]

    operations = [
        migrations.AlterField(
            model_name="receipt",
            name="file",
            field=models.FileField(blank=True, upload_to="receipts/"),
        ),
        migrations.AlterField(
            model_name="receipt",
            name="telegram_file_id",
            field=models.CharField(
                blank=True,
                help_text="Telegram file_id. Bot API download URLs expire; this id does not.",
                max_length=128,
            ),
        ),
        migrations.AlterField(
            model_name="purchaseitem",
            name="name",
            field=models.CharField(help_text="Printed OCR text.", max_length=255),
        ),
        migrations.AddField(
            model_name="purchaseitem",
            name="title",
            field=models.CharField(
                blank=True,
                help_text="Human label, e.g. 'beef mince' instead of 'BURGER M VACUN'.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="purchaseitem",
            name="barcode",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name="purchaseitem",
            name="telegram_photo_file_id",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="purchaseitem",
            name="transaction",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="purchase_items",
                to="core.transaction",
            ),
        ),
        migrations.AddField(
            model_name="telegramlink",
            name="pending_item_id",
            field=models.IntegerField(
                blank=True,
                help_text="Next Telegram photo is stored as this purchase item's picture.",
                null=True,
            ),
        ),
        migrations.RunPython(backfill_item_transactions, migrations.RunPython.noop),
    ]
