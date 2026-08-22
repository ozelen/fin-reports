from django.db import migrations, models
from django.db.models.functions import Lower

_IGNORED = (
    "swap",
    "cashout",
    "cash-out",
    "cash out",
    "casin",
    "cashin",
    "cash-in",
    "cash in",
)


def mark_internal_tags(apps, schema_editor):
    Tag = apps.get_model("core", "Tag")
    Tag.objects.annotate(n=Lower("name")).filter(n__in=_IGNORED).update(
        ignore_stats=True
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0021_taxprofile_hourly"),
    ]

    operations = [
        migrations.AddField(
            model_name="tag",
            name="ignore_stats",
            field=models.BooleanField(
                default=False,
                help_text="Hide this tag from dashboard, budgets, and other totals (swap, cash in/out).",
            ),
        ),
        migrations.RunPython(mark_internal_tags, migrations.RunPython.noop),
    ]
