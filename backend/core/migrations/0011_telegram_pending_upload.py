from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_pending_tx_item_tags"),
    ]

    operations = [
        migrations.AddField(
            model_name="telegramlink",
            name="pending_upload_id",
            field=models.IntegerField(
                blank=True,
                help_text="Statement waiting for the user to pick an account.",
                null=True,
            ),
        ),
    ]
