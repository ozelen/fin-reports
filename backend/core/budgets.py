"""Recurring tag budgets: period actuals + projected balance."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.db.models import Q

from .criteria import cadence_factor, period_range
from .fx import Converter, exclude_ignored, summarize_eur
from .models import Account, Budget, Recurrence, Tag, Transaction
from .recurrences import remaining_dates

_ZERO = Decimal("0")
_TOP_UNPLANNED = 8


def _money(value):
    if value is None:
        return None
    return float(value)


def account_balances(user):
    """Effective balance per account (credit cards: available − limit)."""
    accounts = list(Account.objects.filter(owner=user))
    if not accounts:
        return [], _ZERO, False
    today = dt.date.today()
    conv = Converter([today], [a.currency for a in accounts])
    rows = []
    total = _ZERO
    converted = False
    for account in accounts:
        native = account.effective_balance or _ZERO
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
                "balance": _money(account.balance or _ZERO),
                "credit_limit": _money(account.credit_limit),
                "effective": _money(native),
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


def _ratio(actual, amount):
    if actual is None:
        return None
    if not amount:
        return 1.0 if actual else 0.0
    return float(actual / amount)


def _line(
    *,
    row_id,
    source,
    name,
    kind,
    period,
    amount,
    actual,
    is_active,
    start,
    end,
    count,
    tag=None,
    tag_name=None,
    tag_color=None,
    account=None,
    account_label=None,
    budget_id=None,
    recurrence_id=None,
    group="budget",
):
    remaining = None if actual is None else max(_ZERO, amount - actual)
    return {
        "id": row_id,
        "source": source,
        "group": group,
        "name": name,
        "budget_id": budget_id,
        "recurrence_id": recurrence_id,
        "tag": tag,
        "tag_name": tag_name,
        "tag_color": tag_color,
        "account": account,
        "account_label": account_label,
        "period": period,
        "kind": kind,
        "amount": _money(amount),
        "is_active": is_active,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "actual": _money(actual),
        "remaining": _money(remaining),
        "ratio": _ratio(actual, amount),
        "count": count,
    }


def _iter_months(start: dt.date, end: dt.date):
    year, month = start.year, start.month
    while dt.date(year, month, 1) <= end:
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _irpf_cover_months(due: dt.date) -> set[tuple[int, int]]:
    """Months to set aside 1/3 of a 130 installment (the quarter being earned)."""
    if due.month == 1:
        year = due.year - 1
        return {(year, 10), (year, 11), (year, 12)}
    months = {4: (1, 2, 3), 7: (4, 5, 6), 10: (7, 8, 9)}.get(due.month)
    if not months:
        return set()
    return {(due.year, month) for month in months}


def _is_irpf_rec(rec) -> bool:
    return rec.category == Recurrence.CAT_TAX and (rec.name or "").startswith(
        "IRPF Pago Fraccionado"
    )


def rec_planned(rec, start: dt.date, end: dt.date) -> Decimal:
    """Cadence share of |amount| in [start, end], 0 if the rec hasn't started."""
    if rec.start_date and rec.start_date > end:
        return _ZERO
    if rec.end_date and rec.end_date < start:
        return _ZERO
    return abs(rec.amount) * cadence_factor(rec.frequency, start, end)


def irpf_monthly_in_window(recs, start: dt.date, end: dt.date) -> Decimal:
    """Unpaid 130 ÷ 3 for each overlapping earn month in [start, end]."""
    total = _ZERO
    view = set(_iter_months(start, end))
    for rec in recs:
        if not rec.is_active or not _is_irpf_rec(rec):
            continue
        share = abs(rec.amount) / 3
        cover = _irpf_cover_months(rec.start_date)
        total += share * sum(1 for month in view if month in cover)
    return total


def status(user, start: dt.date | None = None, end: dt.date | None = None) -> dict:
    today = dt.date.today()
    if start is None or end is None:
        start, end = period_range("month", today)
    as_of = min(end, today)
    accounts, current, converted = account_balances(user)
    remaining_income = _ZERO
    remaining_out = _ZERO
    planned_income = _ZERO
    planned_spend = _ZERO
    salary_planned = _ZERO
    tax_planned = _ZERO
    lines = []
    for budget in Budget.objects.filter(owner=user).select_related("tag", "account"):
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
        planned = budget.amount * cadence_factor(budget.period, start, end)
        line = _line(
            row_id=f"b-{budget.id}",
            source="budget",
            name=budget.tag.name,
            kind=budget.kind,
            period=budget.period,
            amount=planned,
            actual=actual if actual is not None else _ZERO,
            is_active=budget.is_active,
            start=start,
            end=end,
            count=summary.get("count") or 0,
            tag=budget.tag_id,
            tag_name=budget.tag.name,
            tag_color=budget.tag.color,
            account=budget.account_id,
            account_label=budget.account.name if budget.account else None,
            budget_id=budget.id,
            group="salary" if budget.kind == Budget.KIND_INCOME else "budget",
        )
        lines.append(line)
        if budget.is_active:
            if budget.kind == Budget.KIND_INCOME:
                planned_income += planned
                salary_planned += planned
            else:
                planned_spend += planned
            remaining = line["remaining"]
            if remaining is not None:
                if budget.kind == Budget.KIND_INCOME:
                    remaining_income += Decimal(str(remaining))
                else:
                    remaining_out += Decimal(str(remaining))

    recs = list(
        Recurrence.objects.filter(owner=user)
        .select_related("account")
        .prefetch_related("tags", "occurrences")
    )
    rec_conv = Converter([as_of], [r.currency for r in recs] or ["EUR"])
    irpf_recs = [rec for rec in recs if _is_irpf_rec(rec)]
    for rec in recs:
        if _is_irpf_rec(rec):
            continue
        native = rec_planned(rec, start, end)
        planned = rec_conv.to_eur(native, rec.currency or "EUR", as_of)
        if planned is None:
            planned = native if (rec.currency or "EUR").upper() == "EUR" else _ZERO
        else:
            if (rec.currency or "EUR").upper() != "EUR":
                converted = True
        kind = (
            Budget.KIND_INCOME
            if rec.amount >= 0 or rec.category == Recurrence.CAT_INCOME
            else Budget.KIND_SPEND
        )
        if rec.category == Recurrence.CAT_TAX:
            group = "tax"
        elif rec.category == Recurrence.CAT_INCOME or kind == Budget.KIND_INCOME:
            group = "salary"
        else:
            group = "recurring"
        tags = list(rec.tags.all())
        tag = tags[0] if tags else None
        qs = Transaction.objects.filter(
            owner=user,
            operation_date__gte=start,
            operation_date__lte=end,
        )
        if rec.account_id:
            qs = qs.filter(account=rec.account)
        if tag:
            qs = qs.filter(Q(recurrence=rec) | Q(tags=tag))
        else:
            qs = qs.filter(recurrence=rec)
        qs = exclude_ignored(qs)
        summary = summarize_eur(qs)
        actual = _actual(summary, kind)
        line = _line(
            row_id=f"r-{rec.id}",
            source="recurrence",
            name=rec.name,
            kind=kind,
            period=rec.frequency,
            amount=planned,
            actual=actual if actual is not None else _ZERO,
            is_active=rec.is_active,
            start=start,
            end=end,
            count=summary.get("count") or 0,
            tag=tag.id if tag else None,
            tag_name=tag.name if tag else None,
            tag_color=tag.color if tag else None,
            account=rec.account_id,
            account_label=rec.account.name if rec.account else None,
            recurrence_id=rec.id,
            group=group,
        )
        lines.append(line)
        if rec.is_active:
            if kind == Budget.KIND_INCOME:
                planned_income += planned
                salary_planned += planned
            else:
                planned_spend += planned
                if group == "tax":
                    tax_planned += planned
            remaining = line["remaining"]
            if remaining is not None:
                if kind == Budget.KIND_INCOME:
                    remaining_income += Decimal(str(remaining))
                else:
                    remaining_out += Decimal(str(remaining))

    irpf_native = irpf_monthly_in_window(irpf_recs, start, end)
    if irpf_native:
        template = next((rec for rec in irpf_recs if rec.is_active), irpf_recs[0])
        irpf_planned = rec_conv.to_eur(irpf_native, template.currency or "EUR", as_of)
        if irpf_planned is None:
            irpf_planned = (
                irpf_native if (template.currency or "EUR").upper() == "EUR" else _ZERO
            )
        irpf_line = _line(
            row_id="irpf-monthly",
            source="irpf",
            name="IRPF Pago Fraccionado",
            kind=Budget.KIND_SPEND,
            period=Recurrence.FREQ_MONTH,
            amount=irpf_planned,
            actual=_ZERO,
            is_active=True,
            start=start,
            end=end,
            count=0,
            account=template.account_id,
            account_label=template.account.name if template.account else None,
            group="tax",
        )
        lines.append(irpf_line)
        planned_spend += irpf_planned
        tax_planned += irpf_planned
        remaining_out += Decimal(str(irpf_line["remaining"] or 0))

    tax_set_aside = _ZERO
    for rec in recs:
        if not rec.is_active or rec.category != Recurrence.CAT_TAX:
            continue
        cap = dt.date(today.year + 1, 1, 31)
        horizon = rec.end_date or cap
        if horizon > cap:
            horizon = cap
        n = len(remaining_dates(rec, today - dt.timedelta(days=1), horizon))
        native = abs(rec.amount) * n
        eur = rec_conv.to_eur(native, rec.currency or "EUR", as_of)
        if eur is None:
            eur = native if (rec.currency or "EUR").upper() == "EUR" else _ZERO
        tax_set_aside += eur

    shown_tags = {row["tag"] for row in lines if row.get("tag")}
    factor = cadence_factor(Budget.PERIOD_MONTH, start, end) or 1
    unplanned = []
    tag_qs = Tag.objects.filter(
        owner=user,
        ignore_stats=False,
        transactions__owner=user,
        transactions__operation_date__gte=start,
        transactions__operation_date__lte=end,
        transactions__recurrence__isnull=True,
        transactions__amount__lt=0,
    ).distinct()
    if shown_tags:
        tag_qs = tag_qs.exclude(id__in=shown_tags)
    for tag in tag_qs:
        qs = exclude_ignored(
            Transaction.objects.filter(
                owner=user,
                tags=tag,
                recurrence__isnull=True,
                operation_date__gte=start,
                operation_date__lte=end,
            )
        )
        summary = summarize_eur(qs)
        actual = _actual(summary, Budget.KIND_SPEND)
        if not actual:
            continue
        line = _line(
            row_id=f"u-{tag.id}",
            source="unplanned",
            name=tag.name,
            kind=Budget.KIND_SPEND,
            period=Budget.PERIOD_MONTH,
            amount=_ZERO,
            actual=actual,
            is_active=True,
            start=start,
            end=end,
            count=summary.get("count") or 0,
            tag=tag.id,
            tag_name=tag.name,
            tag_color=tag.color,
            group="unplanned",
        )
        line["suggest_amount"] = _money(actual / factor)
        unplanned.append(line)
    unplanned.sort(key=lambda row: -(row["actual"] or 0))
    lines.extend(unplanned[:_TOP_UNPLANNED])

    order = {"salary": 0, "tax": 1, "recurring": 2, "budget": 3, "unplanned": 4}
    lines.sort(
        key=lambda row: (
            order.get(row["group"], 9),
            -(row["actual"] or 0) if row["group"] == "unplanned" else 0,
            row["name"] or "",
        )
    )

    return {
        "as_of": as_of.isoformat(),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "current_balance": _money(current),
        "planned_income": _money(planned_income),
        "planned_spend": _money(planned_spend),
        "planned_net": _money(planned_income - planned_spend),
        "salary": _money(salary_planned),
        "tax": _money(tax_planned),
        "after_tax": _money(salary_planned - tax_planned),
        "tax_set_aside": _money(tax_set_aside),
        "available_after_tax": _money(current - tax_set_aside),
        "remaining_income": _money(remaining_income),
        "remaining_spend": _money(remaining_out),
        "projected_balance": _money(current + remaining_income - remaining_out),
        "converted": converted,
        "accounts": accounts,
        "budgets": lines,
    }
