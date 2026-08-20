import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_item_title_barcode_photo"),
    ]

    operations = [
        migrations.AlterField(
            model_name="transaction",
            name="upload",
            field=models.ForeignKey(
                blank=True,
                help_text="Null until a bank statement row is absorbed.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="transactions",
                to="core.upload",
            ),
        ),
        migrations.AddField(
            model_name="purchaseitem",
            name="tags",
            field=models.ManyToManyField(
                blank=True, related_name="purchase_items", to="core.tag"
            ),
        ),
    ]
