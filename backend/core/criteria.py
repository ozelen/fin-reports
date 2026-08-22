"""Shared 'criteria' logic reused by the transaction filter, smart folders,
and rules. A criteria dict is a subset of the transaction filter params."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal


def _quarter_bounds(year: int, q: int) -> tuple[dt.date, dt.date]:
    start_month = {1: 1, 2: 4, 3: 7, 4: 10}[q]
    start = dt.date(year, start_month, 1)
    if q == 4:
        end = dt.date(year, 12, 31)
    else:
        end = dt.date(year, start_month + 3, 1) - dt.timedelta(days=1)
    return start, end


def quarter_range(quarter, year=None, today: dt.date | None = None):
    """Map a quarter token to a (date_from, date_to) tuple, or None.

    Accepts: this/current, prev/previous/last, q1..q4 (or 1..4).
    """
    if quarter is None or quarter == "":
        return None
    today = today or dt.date.today()
    token = str(quarter).strip().lower()
    current_q = (today.month - 1) // 3 + 1

    if token in ("this", "current", "this_quarter"):
        y, q = today.year, current_q
    elif token in ("prev", "previous", "last", "prev_quarter"):
        if current_q == 1:
            y, q = today.year - 1, 4
        else:
            y, q = today.year, current_q - 1
    elif token in ("q1", "q2", "q3", "q4", "1", "2", "3", "4"):
        q = int(token[-1])
        y = int(year) if year else today.year
    else:
        return None
    return _quarter_bounds(y, q)


def period_range(period, today: dt.date | None = None):
    """Window for a recurring budget: week (Mon–Sun), calendar month, or year."""
    today = today or dt.date.today()
    if period == "week":
        start = today - dt.timedelta(days=today.weekday())
        return start, start + dt.timedelta(days=6)
    if period == "year":
        return dt.date(today.year, 1, 1), dt.date(today.year, 12, 31)
    if period == "quarter":
        return _quarter_bounds(today.year, (today.month - 1) // 3 + 1)
    if period == "month":
        start = today.replace(day=1)
        if start.month == 12:
            end = dt.date(start.year, 12, 31)
        else:
            end = dt.date(start.year, start.month + 1, 1) - dt.timedelta(days=1)
        return start, end
    return None


def view_window(*, year=None, month=None, quarter=None, today: dt.date | None = None):
    """Calendar month, quarter, or year. Month wins over quarter; year is the rest."""
    today = today or dt.date.today()
    y = int(year) if year not in (None, "") else today.year
    if month not in (None, ""):
        m = int(month)
        start = dt.date(y, m, 1)
        if m == 12:
            return start, dt.date(y, 12, 31)
        return start, dt.date(y, m + 1, 1) - dt.timedelta(days=1)
    if quarter not in (None, ""):
        token = str(quarter).strip().lower().lstrip("q")
        return _quarter_bounds(y, int(token))
    return dt.date(y, 1, 1), dt.date(y, 12, 31)


def cadence_factor(cadence, start: dt.date, end: dt.date):
    """How many cadence units (or a fraction) fit in [start, end]."""
    unit = period_range(cadence, start)
    if not unit:
        return Decimal("1")
    unit_days = (unit[1] - unit[0]).days + 1
    view_days = (end - start).days + 1
    if view_days < unit_days:
        return Decimal(view_days) / Decimal(unit_days)
    if cadence == "week":
        day = start - dt.timedelta(days=start.weekday())
        n = 0
        while day <= end:
            if day + dt.timedelta(days=6) >= start:
                n += 1
            day += dt.timedelta(days=7)
        return Decimal(n)
    if cadence == "month":
        return Decimal((end.year - start.year) * 12 + end.month - start.month + 1)
    if cadence == "quarter":
        first = start.year * 4 + (start.month - 1) // 3
        last = end.year * 4 + (end.month - 1) // 3
        return Decimal(last - first + 1)
    if cadence == "year":
        return Decimal(end.year - start.year + 1)
    return Decimal("1")


def apply_criteria(queryset, criteria: dict | None):
    """Filter a Transaction queryset by a stored criteria dict.

    List values (e.g. `tags`) are normalized to comma-separated strings so the
    CharFilter-based filterset parses them the same way it does query params.
    """
    from .filters import TransactionFilter

    data = {}
    for key, value in (criteria or {}).items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (list, tuple)):
            value = ",".join(str(v) for v in value)
        data[key] = value
    if not data:
        return queryset
    return TransactionFilter(data=data, queryset=queryset).qs
