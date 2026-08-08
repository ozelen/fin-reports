import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def attach_default_account(apps, schema_editor):
    """Give every owner that already has data a 'Santander' account and
    attach all of their existing uploads and transactions to it."""
    Account = apps.get_model("core", "Account")
    Upload = apps.get_model("core", "Upload")
    Transaction = apps.get_model("core", "Transaction")

    owner_ids = set(Upload.objects.values_list("owner_id", flat=True)) | set(
        Transaction.objects.values_list("owner_id", flat=True)
    )
    for owner_id in owner_ids:
        account, _ = Account.objects.get_or_create(
            owner_id=owner_id,
            name="Santander",
            defaults={"bank": "Santander", "is_default": True},
        )
        Upload.objects.filter(owner_id=owner_id, account__isnull=True).update(
            account=account
        )
        Transaction.objects.filter(owner_id=owner_id, account__isnull=True).update(
            account=account
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_rule_tag_transactiontag_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Account",
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
                ("name", models.CharField(max_length=120)),
                ("bank", models.CharField(blank=True, max_length=120)),
                ("iban", models.CharField(blank=True, max_length=34)),
                ("currency", models.CharField(default="EUR", max_length=8)),
                ("is_default", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="accounts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.AddConstraint(
            model_name="account",
            constraint=models.UniqueConstraint(
                fields=("owner", "name"), name="uniq_owner_account"
            ),
        ),
        migrations.AddField(
            model_name="upload",
            name="account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="uploads",
                to="core.account",
            ),
        ),
        migrations.AddField(
            model_name="transaction",
            name="account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="transactions",
                to="core.account",
            ),
        ),
        migrations.RunPython(attach_default_account, noop),
    ]
