from django.db import migrations, models


def classify_existing_accounts(apps, schema_editor):
    Account = apps.get_model("core", "Account")
    Account.objects.filter(name__iexact="Monobank").update(group="personal")
    Account.objects.exclude(name__iexact="Monobank").update(group="family")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_documents"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="group",
            field=models.CharField(
                choices=[("family", "Family"), ("personal", "Personal")],
                default="family",
                max_length=20,
            ),
        ),
        migrations.AlterModelOptions(
            name="account",
            options={"ordering": ["group", "name"]},
        ),
        migrations.RunPython(classify_existing_accounts, noop),
    ]
