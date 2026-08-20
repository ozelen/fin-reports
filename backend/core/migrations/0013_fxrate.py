from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_receipt_needs_parse"),
    ]

    operations = [
        migrations.CreateModel(
            name="FxRate",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("date", models.DateField(db_index=True)),
                ("currency", models.CharField(max_length=8)),
                (
                    "uah_per_unit",
                    models.DecimalField(decimal_places=8, max_digits=18),
                ),
            ],
            options={
                "ordering": ["-date", "currency"],
            },
        ),
        migrations.AddConstraint(
            model_name="fxrate",
            constraint=models.UniqueConstraint(
                fields=("date", "currency"), name="uniq_fx_date_currency"
            ),
        ),
    ]
