"""Recurring tag budgets: period actuals + projected balance."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from .criteria import period_range
from .fx import Converter, summarize_eur
from .models import Account, Budget, Transaction

_ZERO = Decimal("0")


def _money(value):
    if value is None:
        return None
    return float(value)


def account_balances(user):
    """Stored balance per account (statement last row, then manual edits/transfers)."""
    accounts = list(Account.objects.filter(owner=user))
    if not accounts:
        return [], _ZERO, False
    today = dt.date.today()
    conv = Converter([today], [a.currency for a in accounts])
    rows = []
    total = _ZERO
    converted = False
    for account in accounts:
        native = account.balance or _ZERO
        ccy = account.currency or "EUR"
        eur = conv.to_eur(native, ccy, today)
        if eur is not None:
            total += eur
            if ccy.upper() != "EUR":
                converted = True
        rows.append(
            {
                "id": account.id,
                "name": account.name,
                "kind": account.kind,
                "balance": _money(native),
                "currency": ccy,
                "eur": _money(eur),
            }
        )
    return rows, total, converted


def _actual(summary, kind) -> Decimal | None:
    if kind == Budget.KIND_INCOME:
        value = summary.get("income")
        return None if value is None else Decimal(str(value))
    value = summary.get("expense")
    if value is None:
        return None
    return abs(Decimal(str(value)))


def status(user, as_of: dt.date | None = None) -> dict:
    as_of = as_of or dt.date.today()
    accounts, current, converted = account_balances(user)
    remaining_income = _ZERO
    remaining_out = _ZERO
    lines = []
    for budget in Budget.objects.filter(owner=user).select_related("tag", "account"):
        window = period_range(budget.period, as_of)
        if not window:
            continue
        start, end = window
        qs = Transaction.objects.filter(
            owner=user,
            tags=budget.tag,
            operation_date__gte=start,
            operation_date__lte=end,
        )
        if budget.account_id:
            qs = qs.filter(account=budget.account)
        summary = summarize_eur(qs)
        actual = _actual(summary, budget.kind)
        remaining = None if actual is None else max(_ZERO, budget.amount - actual)
        if budget.is_active and remaining is not None:
            if budget.kind == Budget.KIND_INCOME:
                remaining_income += remaining
            else:
                remaining_out += remaining
        if actual is None or not budget.amount:
            ratio = None if actual is None else (1.0 if actual else 0.0)
        else:
            ratio = float(actual / budget.amount)
        lines.append(
            {
                "id": budget.id,
                "tag": budget.tag_id,
                "tag_name": budget.tag.name,
                "tag_color": budget.tag.color,
                "account": budget.account_id,
                "account_label": budget.account.name if budget.account else None,
                "period": budget.period,
                "kind": budget.kind,
                "amount": _money(budget.amount),
                "is_active": budget.is_active,
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "actual": _money(actual),
                "remaining": _money(remaining),
                "ratio": ratio,
                "count": summary.get("count") or 0,
            }
        )

    return {
        "as_of": as_of.isoformat(),
        "current_balance": _money(current),
        "remaining_income": _money(remaining_income),
        "remaining_spend": _money(remaining_out),
        "projected_balance": _money(current + remaining_income - remaining_out),
        "converted": converted,
        "accounts": accounts,
        "budgets": lines,
    }
