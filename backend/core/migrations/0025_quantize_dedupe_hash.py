import hashlib
from decimal import Decimal

from django.db import migrations


def _money(value) -> str:
    if value is None:
        return "None"
    return f"{Decimal(value).quantize(Decimal('0.01'))}"


def _hash(tx) -> str:
    key = f"{tx.operation_date}|{_money(tx.amount)}|{(tx.concept or '').strip().casefold()}|{_money(tx.balance)}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def quantize_dedupe(apps, schema_editor):
    Transaction = apps.get_model("core", "Transaction")
    updates = []
    for tx in Transaction.objects.filter(upload_id__isnull=False).iterator():
        if (tx.metadata or {}).get("transfer"):
            continue
        new = _hash(tx)
        if tx.dedupe_hash == new:
            continue
        tx.dedupe_hash = new
        updates.append(tx)
    if updates:
        Transaction.objects.bulk_update(updates, ["dedupe_hash"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0024_casefold_dedupe_hash"),
    ]

    operations = [
        migrations.RunPython(quantize_dedupe, migrations.RunPython.noop),
    ]
