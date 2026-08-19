from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0006_account_group"),
    ]

    operations = [
        migrations.CreateModel(
            name="Receipt",
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
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("receipt", "Receipt"),
                            ("invoice", "Invoice"),
                            ("other", "Other"),
                        ],
                        default="receipt",
                        max_length=20,
                    ),
                ),
                ("merchant", models.CharField(blank=True, max_length=255)),
                (
                    "amount",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=14, null=True
                    ),
                ),
                ("currency", models.CharField(default="EUR", max_length=8)),
                ("document_date", models.DateField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("original_filename", models.CharField(blank=True, max_length=255)),
                ("mime_type", models.CharField(blank=True, max_length=100)),
                ("file", models.FileField(upload_to="receipts/")),
                ("extracted", models.JSONField(blank=True, default=dict)),
                (
                    "source",
                    models.CharField(
                        choices=[("telegram", "Telegram"), ("web", "Web")],
                        default="telegram",
                        max_length=20,
                    ),
                ),
                ("telegram_file_id", models.CharField(blank=True, max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="receipts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "transaction",
                    models.ForeignKey(
                        blank=True,
                        help_text="Set once the matching bank transaction is known.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="receipts",
                        to="core.transaction",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="TelegramLink",
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
                ("telegram_user_id", models.BigIntegerField(unique=True)),
                ("chat_id", models.BigIntegerField()),
                ("messages", models.JSONField(blank=True, default=list)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="telegram_links",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="receipt",
            index=models.Index(
                fields=["owner", "transaction"], name="core_receip_owner_i_73ce80_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="receipt",
            index=models.Index(
                fields=["owner", "document_date"], name="core_receip_owner_i_c18f0e_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="telegramlink",
            index=models.Index(
                fields=["telegram_user_id"], name="core_telegr_telegra_5109d9_idx"
            ),
        ),
    ]
