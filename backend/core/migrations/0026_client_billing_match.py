from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0025_quantize_dedupe_hash"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="active_from",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="client",
            name="active_to",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="client",
            name="billing_unit",
            field=models.CharField(
                choices=[("hour", "Hour"), ("day", "Day")],
                default="hour",
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="client",
            name="match_text",
            field=models.CharField(
                blank=True,
                help_text="Bank counterparty/concept text used to attach salary payments.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="client",
            name="short_name",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="invoice",
            name="unit",
            field=models.CharField(blank=True, default="hour", max_length=8),
        ),
        migrations.AddField(
            model_name="transaction",
            name="client",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="payments",
                to="core.client",
            ),
        ),
    ]
