from django.db import migrations, models


def switch_to_hours(apps, schema_editor):
    TaxProfile = apps.get_model("core", "TaxProfile")
    TaxProfile.objects.update(income_from="hours", hourly_rate=30, hours_per_day=8)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0020_account_credit_limit"),
    ]

    operations = [
        migrations.AddField(
            model_name="taxprofile",
            name="hourly_rate",
            field=models.DecimalField(decimal_places=2, default=30, max_digits=12),
        ),
        migrations.AddField(
            model_name="taxprofile",
            name="hours_per_day",
            field=models.PositiveSmallIntegerField(default=8),
        ),
        migrations.AddField(
            model_name="taxprofile",
            name="hours_overrides",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name="taxprofile",
            name="income_from",
            field=models.CharField(
                choices=[
                    ("hours", "Hourly × working days"),
                    ("invoices", "Issued invoices"),
                    ("tags", "Tagged bank income"),
                ],
                default="hours",
                max_length=12,
            ),
        ),
        migrations.RunPython(switch_to_hours, migrations.RunPython.noop),
    ]
