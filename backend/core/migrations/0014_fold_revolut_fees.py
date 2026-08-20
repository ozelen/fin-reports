import hashlib
from decimal import Decimal, InvalidOperation

from django.db import migrations


def fold_fees(apps, schema_editor):
    Transaction = apps.get_model("core", "Transaction")
    for tx in Transaction.objects.exclude(metadata={}).iterator():
        meta = tx.metadata or {}
        if meta.get("fee_in_amount"):
            continue
        account = tx.account
        label = f"{getattr(account, 'name', '')} {getattr(account, 'bank', '')}".lower()
        if "revolut" not in label:
            continue
        raw = meta.get("commission")
        if not raw:
            continue
        try:
            fee = Decimal(str(raw))
        except InvalidOperation:
            continue
        if not fee:
            continue
        tx.amount = tx.amount - fee
        key = f"{tx.operation_date}|{tx.amount}|{tx.concept}|{tx.balance}"
        tx.dedupe_hash = hashlib.sha256(key.encode()).hexdigest()
        meta["fee_in_amount"] = True
        tx.metadata = meta
        tx.save(update_fields=["amount", "dedupe_hash", "metadata"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_fxrate"),
    ]

    operations = [
        migrations.RunPython(fold_fees, migrations.RunPython.noop),
    ]
