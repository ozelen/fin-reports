from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0022_tag_ignore_stats"),
    ]

    operations = [
        migrations.AlterField(
            model_name="budget",
            name="period",
            field=models.CharField(
                choices=[
                    ("week", "Week"),
                    ("month", "Month"),
                    ("quarter", "Quarter"),
                    ("year", "Year"),
                ],
                default="month",
                max_length=8,
            ),
        ),
    ]
