"""Account balances and manual transfers."""
from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal

from django.db import transaction as db_transaction
from django.db.models import F

from .models import Account, Transaction


def end_running_balance(items) -> Decimal | None:
    """Posted balance after the last movement on the newest date.

    Bank files are newest-first, so insert id is the wrong tie-break: same-day
    rows like +900 (968.34) then −851.81 then −24.99 (91.54) must end at 91.54.
    A follows B when A.balance - A.amount == B.balance; the end has no follower.
    """
    dated = []
    for t in items:
        if isinstance(t, dict):
            day, amount, balance = t.get("operation_date"), t.get("amount"), t.get("balance")
        else:
            day, amount, balance = t.operation_date, t.amount, t.balance
        if day is None or amount is None or balance is None:
            continue
        dated.append((day, amount, balance))
    if not dated:
        return None
    latest = max(day for day, _, _ in dated)
    day_rows = [(amount, balance) for day, amount, balance in dated if day == latest]
    if len(day_rows) == 1:
        return day_rows[0][1]
    prev = {balance - amount for amount, balance in day_rows}
    ends = [balance for amount, balance in day_rows if balance not in prev]
    return ends[0] if len(ends) == 1 else None


def apply_statement_balance(account: Account | None, rows=None) -> None:
    """Set stored balance from the statement rows, else the account ledger."""
    if account is None:
        return
    balance = end_running_balance(rows or ())
    if balance is None:
        balance = end_running_balance(
            account.transactions.filter(balance__isnull=False).only(
                "operation_date", "amount", "balance"
            )
        )
    if balance is None:
        return
    account.balance = balance
    account.save(update_fields=["balance"])


# ponytail: same-currency only. Cross-currency = edit both balances by hand
# until FX on transfers is worth a rate picker.


def book_transfer(user, src: Account, dst: Account, amount, day, concept: str = ""):
    """Move `amount` from src to dst. Two ledger rows, both balances updated."""
    amount = abs(Decimal(amount))
    pair = uuid.uuid4().hex
    concept = (concept or "").strip() or f"{src.name} → {dst.name}"
    with db_transaction.atomic():
        Transaction.objects.create(
            owner=user,
            account=src,
            operation_date=day,
            concept=concept,
            counterparty=dst.name,
            amount=-amount,
            currency=src.currency,
            metadata={"transfer": pair, "to": dst.id},
            dedupe_hash=hashlib.sha256(f"transfer:{pair}:out".encode()).hexdigest(),
        )
        Transaction.objects.create(
            owner=user,
            account=dst,
            operation_date=day,
            concept=concept,
            counterparty=src.name,
            amount=amount,
            currency=dst.currency,
            metadata={"transfer": pair, "from": src.id},
            dedupe_hash=hashlib.sha256(f"transfer:{pair}:in".encode()).hexdigest(),
        )
        Account.objects.filter(pk=src.pk).update(balance=F("balance") - amount)
        Account.objects.filter(pk=dst.pk).update(balance=F("balance") + amount)
        src.refresh_from_db(fields=["balance"])
        dst.refresh_from_db(fields=["balance"])
    return src, dst


def _self_check():
    import datetime as dt
    from types import SimpleNamespace as N

    day = dt.date(2026, 8, 20)
    rows = [
        N(operation_date=day, amount=Decimal("-24.99"), balance=Decimal("91.54")),
        N(operation_date=day, amount=Decimal("-851.81"), balance=Decimal("116.53")),
        N(operation_date=day, amount=Decimal("900.00"), balance=Decimal("968.34")),
    ]
    assert end_running_balance(rows) == Decimal("91.54")
    assert end_running_balance(list(reversed(rows))) == Decimal("91.54")
    assert end_running_balance(rows[2:]) == Decimal("968.34")
    print("ok")


if __name__ == "__main__":
    _self_check()
