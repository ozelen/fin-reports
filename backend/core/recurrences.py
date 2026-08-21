"""Scheduled recurrences: cadence, matching, attach."""
from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal

from .models import Account, Recurrence, Transaction, TransactionTag
from .receipts import merchant_overlap

DATE_WINDOWS = {
    Recurrence.FREQ_WEEK: 2,
    Recurrence.FREQ_MONTH: 5,
    Recurrence.FREQ_QUARTER: 10,
    Recurrence.FREQ_YEAR: 15,
}
_FLOOR = Decimal("0.02")


def date_window(rec: Recurrence) -> int:
    return DATE_WINDOWS.get(rec.frequency, 5)


def clamp_day(year: int, month: int, day: int) -> dt.date:
    last = calendar.monthrange(year, month)[1]
    return dt.date(year, month, max(1, min(int(day), last)))


def add_months(year: int, month: int, months: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + months
    return idx // 12, idx % 12 + 1


def iter_occurrences(
    rec: Recurrence,
    start: dt.date | None = None,
    end: dt.date | None = None,
    *,
    limit: int = 600,
):
    """Yield expected dates in [start, end], aligned to cadence from start_date."""
    origin = rec.start_date
    horizon = rec.end_date
    start = start or origin
    if end is None:
        end = horizon or dt.date(start.year + 3, 12, 31)
    if horizon and end > horizon:
        end = horizon
    if start > end:
        return

    due = int(rec.due_day)
    n = 0
    if rec.frequency == Recurrence.FREQ_WEEK:
        weekday = max(0, min(due, 6))
        cursor = origin
        while cursor.weekday() != weekday:
            cursor += dt.timedelta(days=1)
        while cursor <= end and n < limit:
            if cursor >= start:
                yield cursor
                n += 1
            cursor += dt.timedelta(days=7)
        return

    step = {
        Recurrence.FREQ_MONTH: 1,
        Recurrence.FREQ_QUARTER: 3,
        Recurrence.FREQ_YEAR: 12,
    }.get(rec.frequency, 1)
    day = due if rec.frequency != Recurrence.FREQ_WEEK else origin.day
    if day < 1:
        day = 1
    year, month = origin.year, origin.month
    cursor = clamp_day(year, month, day)
    if cursor < origin:
        year, month = add_months(year, month, step)
        cursor = clamp_day(year, month, day)
    while cursor <= end and n < limit:
        if cursor >= start:
            yield cursor
            n += 1
        year, month = add_months(year, month, step)
        cursor = clamp_day(year, month, day)


def on_cadence(rec: Recurrence, day: dt.date) -> bool:
    window = date_window(rec)
    lo = day - dt.timedelta(days=window)
    hi = day + dt.timedelta(days=window)
    return any(abs((occ - day).days) <= window for occ in iter_occurrences(rec, lo, hi))


def amount_within(rec: Recurrence, amount) -> bool:
    expected = Decimal(str(rec.amount))
    got = Decimal(str(amount))
    if expected * got < 0:
        return False
    delta = abs(abs(got) - abs(expected))
    pct = (rec.amount_tolerance_pct or 0) / Decimal("100") * abs(expected)
    return delta <= max(_FLOOR, pct)


def matches(rec: Recurrence, tx: Transaction, *, require_auto: bool = True) -> bool:
    if require_auto and (not rec.auto_match or not rec.is_active):
        return False
    if rec.end_date and tx.operation_date > rec.end_date:
        return False
    if tx.operation_date < rec.start_date - dt.timedelta(days=date_window(rec)):
        return False
    if rec.account_id and tx.account_id and rec.account_id != tx.account_id:
        return False
    if not amount_within(rec, tx.amount):
        return False
    if rec.match_text.strip() and not merchant_overlap(rec.match_text, tx):
        return False
    return on_cadence(rec, tx.operation_date)


def attach(tx: Transaction, rec: Recurrence) -> bool:
    """Link tx to rec and copy tags. Returns True if the FK changed."""
    changed = tx.recurrence_id != rec.id
    if changed:
        tx.recurrence = rec
        tx.save(update_fields=["recurrence"])
    for tag in rec.tags.all():
        TransactionTag.objects.get_or_create(
            transaction=tx,
            tag=tag,
            defaults={"source": TransactionTag.SOURCE_SCHEDULE},
        )
    return changed


def detach(tx: Transaction, rec: Recurrence | None = None) -> None:
    if rec is not None and tx.recurrence_id != rec.id:
        return
    tx.recurrence = None
    tx.save(update_fields=["recurrence"])


def candidate_queryset(rec: Recurrence):
    expected = Decimal(str(rec.amount))
    tol = max(_FLOOR, abs(expected) * (rec.amount_tolerance_pct or 0) / Decimal("100"))
    lo, hi = expected - tol, expected + tol
    qs = Transaction.objects.filter(
        owner=rec.owner,
        amount__gte=min(lo, hi),
        amount__lte=max(lo, hi),
        recurrence__isnull=True,
    )
    if rec.account_id:
        qs = qs.filter(account_id=rec.account_id)
    window = date_window(rec)
    qs = qs.filter(operation_date__gte=rec.start_date - dt.timedelta(days=window))
    if rec.end_date:
        qs = qs.filter(operation_date__lte=rec.end_date + dt.timedelta(days=window))
    return qs


def backfill(rec: Recurrence) -> int:
    attached = 0
    for tx in candidate_queryset(rec).iterator():
        if matches(rec, tx):
            attach(tx, rec)
            attached += 1
    return attached


def suggest(rec: Recurrence, limit: int = 50) -> list[Transaction]:
    hits = []
    for tx in candidate_queryset(rec).order_by("-operation_date", "-id")[:200]:
        if matches(rec, tx):
            hits.append(tx)
            if len(hits) >= limit:
                break
    return hits


def attach_new_recurrences(user, queryset) -> int:
    recs = list(
        Recurrence.objects.filter(
            owner=user, is_active=True, auto_match=True
        ).prefetch_related("tags")
    )
    if not recs:
        return 0
    attached = 0
    for tx in queryset.filter(recurrence__isnull=True):
        hits = [r for r in recs if matches(r, tx)]
        if not hits:
            continue
        hits.sort(
            key=lambda r: (
                abs(abs(tx.amount) - abs(r.amount)),
                -len(r.match_text or ""),
            )
        )
        attach(tx, hits[0])
        attached += 1
    return attached


def _paid_dates(rec: Recurrence) -> list[dt.date]:
    return [tx.operation_date for tx in rec.occurrences.all()]


def next_unpaid(rec: Recurrence, today: dt.date | None = None) -> dt.date | None:
    today = today or dt.date.today()
    window = date_window(rec)
    paid_dates = _paid_dates(rec)
    horizon = rec.end_date or dt.date(today.year + 2, 12, 31)
    for occ in iter_occurrences(rec, rec.start_date, horizon):
        if any(abs((p - occ).days) <= window for p in paid_dates):
            continue
        if occ + dt.timedelta(days=window) >= today:
            return occ
    return None


def last_paid(rec: Recurrence) -> dt.date | None:
    dates = _paid_dates(rec)
    return max(dates) if dates else None


def status_for(rec: Recurrence, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    nxt = next_unpaid(rec, today)
    if nxt is None:
        return "paid"
    window = date_window(rec)
    if nxt < today - dt.timedelta(days=window):
        return "overdue"
    if nxt <= today + dt.timedelta(days=window):
        # due around now; if unpaid it's upcoming until past the window
        if nxt < today:
            return "overdue"
        return "upcoming"
    return "upcoming"


def remaining_dates(
    rec: Recurrence, after: dt.date, until: dt.date
) -> list[dt.date]:
    window = date_window(rec)
    paid = _paid_dates(rec)
    out = []
    for occ in iter_occurrences(rec, after + dt.timedelta(days=1), until):
        if any(abs((p - occ).days) <= window for p in paid):
            continue
        out.append(occ)
    return out


def month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    last = calendar.monthrange(year, month)[1]
    return dt.date(year, month, 1), dt.date(year, month, last)


def next_month_bounds(today: dt.date | None = None) -> tuple[dt.date, dt.date]:
    today = today or dt.date.today()
    year, month = add_months(today.year, today.month, 1)
    return month_bounds(year, month)


def window_remaining(rec: Recurrence, start: dt.date, end: dt.date):
    """Unpaid occurrences in [start, end] and signed remaining amount."""
    dates = remaining_dates(rec, start - dt.timedelta(days=1), end)
    total = Decimal(str(rec.amount or 0)) * len(dates)
    return dates, total


def seed_from_transaction(tx: Transaction, **overrides) -> Recurrence:
    name = overrides.get("name") or (tx.counterparty or tx.concept or "Recurring")[:120]
    frequency = overrides.get("frequency") or Recurrence.FREQ_MONTH
    due_day = overrides.get("due_day")
    if due_day is None:
        due_day = (
            tx.operation_date.weekday()
            if frequency == Recurrence.FREQ_WEEK
            else tx.operation_date.day
        )
    rec = Recurrence.objects.create(
        owner=tx.owner,
        name=name,
        amount=overrides.get("amount", tx.amount),
        currency=overrides.get("currency", tx.currency or "EUR"),
        frequency=frequency,
        due_day=due_day,
        start_date=overrides.get("start_date", tx.operation_date),
        end_date=overrides.get("end_date"),
        account=overrides.get("account", tx.account),
        match_text=overrides.get(
            "match_text", (tx.counterparty or tx.concept or "")[:255]
        ),
        amount_tolerance_pct=overrides.get("amount_tolerance_pct", Decimal("10")),
        auto_match=overrides.get("auto_match", True),
        category=overrides.get("category", Recurrence.CAT_OTHER),
        is_active=overrides.get("is_active", True),
    )
    tag_ids = overrides.get("tags")
    if tag_ids is not None:
        rec.tags.set(tag_ids)
    else:
        rec.tags.set(tx.tags.all())
    rec = Recurrence.objects.prefetch_related("tags").get(pk=rec.pk)
    attach(tx, rec)
    backfill(rec)
    return rec


def stats_map(recs, today: dt.date | None = None) -> dict[int, dict]:
    today = today or dt.date.today()
    next_start, next_end = next_month_bounds(today)
    from .fx import Converter

    conv = Converter([next_start], [r.currency for r in recs])
    out = {}
    for rec in recs:
        dates = _paid_dates(rec)
        nxt_dates, nxt_amt = window_remaining(rec, next_start, next_end)
        if not rec.is_active:
            nxt_dates, nxt_amt = [], Decimal("0")
        eur = conv.to_eur(nxt_amt, rec.currency or "EUR", next_start)
        out[rec.id] = {
            "occurrence_count": len(dates),
            "last_date": max(dates) if dates else None,
            "next_due": next_unpaid(rec, today),
            "status": status_for(rec, today),
            "next_month_count": len(nxt_dates),
            "next_month_remaining": float(nxt_amt),
            "next_month_remaining_eur": float(eur) if eur is not None else None,
        }
    return out


def _money(value):
    if value is None:
        return None
    return float(value)


def forecast(user, recs, today: dt.date | None = None) -> dict:
    """EUR remaining cashflow and leftover balances this / next month."""
    today = today or dt.date.today()
    this_end = month_bounds(today.year, today.month)[1]
    next_start, next_end = next_month_bounds(today)
    active = [r for r in recs if r.is_active]
    from .fx import Converter

    accounts = list(Account.objects.filter(owner=user))
    conv = Converter(
        [today, next_start],
        [a.currency for a in accounts] + [r.currency for r in active] or ["EUR"],
    )

    def add_flow(bucket: dict, rec: Recurrence, start: dt.date, end: dt.date):
        dates, amt = window_remaining(rec, start, end)
        if not dates:
            return
        bucket["count"] += len(dates)
        eur = conv.to_eur(amt, rec.currency or "EUR", start)
        if (rec.currency or "EUR").upper() != "EUR":
            bucket["converted"] = True
        if eur is None:
            bucket["missing_fx"] = True
            return
        if eur >= 0:
            bucket["income"] += eur
        else:
            bucket["expense"] += eur

    def empty_flow():
        return {
            "count": 0,
            "income": Decimal("0"),
            "expense": Decimal("0"),
            "converted": False,
            "missing_fx": False,
        }

    def serialize_flow(bucket: dict, start: dt.date, end: dt.date, leftover_eur) -> dict:
        net = bucket["income"] + bucket["expense"]
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "count": bucket["count"],
            "income": _money(bucket["income"]),
            "expense": _money(bucket["expense"]),
            "net": _money(net),
            "leftover_eur": _money(leftover_eur),
            "converted": bucket["converted"],
            "missing_fx": bucket["missing_fx"],
        }

    this_all = empty_flow()
    next_all = empty_flow()
    by_id = {a.id: {"this": empty_flow(), "next": empty_flow()} for a in accounts}
    unassigned = {"this": empty_flow(), "next": empty_flow()}

    for rec in active:
        add_flow(this_all, rec, today, this_end)
        add_flow(next_all, rec, next_start, next_end)
        dest = by_id.get(rec.account_id) if rec.account_id else None
        dest = dest or unassigned
        add_flow(dest["this"], rec, today, this_end)
        add_flow(dest["next"], rec, next_start, next_end)

    current_eur = Decimal("0")
    converted = False
    missing = False
    account_rows = []
    for account in accounts:
        native = account.effective_balance or Decimal("0")
        ccy = account.currency or "EUR"
        eur = conv.to_eur(native, ccy, today)
        if ccy.upper() != "EUR":
            converted = True
        if eur is None:
            missing = True
            eur_val = Decimal("0")
        else:
            current_eur += eur
            eur_val = eur
        flows = by_id[account.id]
        this_left = eur_val + flows["this"]["income"] + flows["this"]["expense"]
        next_left = this_left + flows["next"]["income"] + flows["next"]["expense"]
        account_rows.append(
            {
                "id": account.id,
                "name": account.name,
                "kind": account.kind,
                "currency": ccy,
                "balance": _money(account.balance or 0),
                "credit_limit": _money(account.credit_limit),
                "effective": _money(native),
                "effective_eur": _money(eur),
                "this_month": serialize_flow(flows["this"], today, this_end, this_left),
                "next_month": serialize_flow(
                    flows["next"], next_start, next_end, next_left
                ),
            }
        )

    this_net = this_all["income"] + this_all["expense"]
    next_net = next_all["income"] + next_all["expense"]
    this_left = current_eur + this_net
    next_left = this_left + next_net

    return {
        "as_of": today.isoformat(),
        "this_month": serialize_flow(this_all, today, this_end, this_left),
        "next_month": serialize_flow(next_all, next_start, next_end, next_left),
        "current_eur": _money(current_eur),
        "converted": converted or this_all["converted"] or next_all["converted"],
        "missing_fx": missing or this_all["missing_fx"] or next_all["missing_fx"],
        "accounts": account_rows,
        "unassigned": {
            "this_month": serialize_flow(
                unassigned["this"],
                today,
                this_end,
                unassigned["this"]["income"] + unassigned["this"]["expense"],
            ),
            "next_month": serialize_flow(
                unassigned["next"],
                next_start,
                next_end,
                unassigned["this"]["income"]
                + unassigned["this"]["expense"]
                + unassigned["next"]["income"]
                + unassigned["next"]["expense"],
            ),
        },
    }
