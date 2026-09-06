import hashlib
from collections import defaultdict

from django.db import migrations


def _old_hash(tx) -> str:
    key = f"{tx.operation_date}|{tx.amount}|{tx.concept}|{tx.balance}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _new_hash(tx) -> str:
    key = f"{tx.operation_date}|{tx.amount}|{(tx.concept or '').strip().casefold()}|{tx.balance}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def casefold_dedupe(apps, schema_editor):
    Transaction = apps.get_model("core", "Transaction")
    groups = defaultdict(list)
    for tx in Transaction.objects.filter(upload_id__isnull=False).iterator():
        if (tx.metadata or {}).get("transfer"):
            continue
        groups[
            (
                tx.owner_id,
                tx.account_id,
                tx.operation_date,
                tx.amount,
                tx.balance,
                (tx.concept or "").strip().casefold(),
            )
        ].append(tx)

    drop_ids = []
    for rows in groups.values():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda t: t.id)
        drop_ids.extend(t.id for t in rows[1:])
    if drop_ids:
        Transaction.objects.filter(id__in=drop_ids).delete()

    updates = []
    for tx in Transaction.objects.iterator():
        if tx.dedupe_hash != _old_hash(tx):
            continue
        new = _new_hash(tx)
        if new == tx.dedupe_hash:
            continue
        tx.dedupe_hash = new
        updates.append(tx)
    if updates:
        Transaction.objects.bulk_update(updates, ["dedupe_hash"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0023_budget_period_quarter"),
    ]

    operations = [
        migrations.RunPython(casefold_dedupe, migrations.RunPython.noop),
    ]
