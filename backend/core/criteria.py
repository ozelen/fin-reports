"""Shared 'criteria' logic reused by the transaction filter, smart folders,
and rules. A criteria dict is a subset of the transaction filter params."""
from __future__ import annotations

import datetime as dt


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
