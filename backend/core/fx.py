"""NBU daily rates → EUR. Cached in FxRate. UAH is the NBU base."""
from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Q, Sum

from .models import FxRate

NBU_URL = "https://bank.gov.ua/NBU_Exchange/exchange_site"
_ZERO = Decimal("0")


def _unique(qs):
    """Drop joins/annotations so Sum(amount) is one row per transaction."""
    return qs.model.objects.filter(pk__in=qs.order_by().values("pk"))


def exclude_ignored(qs):
    """Drop txs tagged to skip charts/totals (swap, cash in/out, …)."""
    return qs.exclude(tags__ignore_stats=True)


class Converter:
    """In-memory NBU quotes for a date/currency set. `to_eur` is identity for EUR."""

    def __init__(self, dates, currencies):
        dates = [d for d in dates if d]
        currencies = {(c or "EUR").upper() for c in currencies}
        self._rates = defaultdict(list)  # currency -> [(date, uah_per_unit), ...]
        if dates and any(c != "EUR" for c in currencies):
            _ensure_rates(dates, currencies)
            needed = {"EUR"} | (currencies - {"EUR", "UAH"})
            for row in FxRate.objects.filter(currency__in=needed).order_by("date"):
                self._rates[row.currency].append((row.date, row.uah_per_unit))

    def to_eur(self, amount, currency, date) -> Decimal | None:
        if amount is None:
            amount = _ZERO
        else:
            amount = Decimal(amount)
        currency = (currency or "EUR").upper()
        if currency == "EUR" or not amount:
            return amount
        if not date:
            return None
        eur_uah = self._uah_per("EUR", date)
        if not eur_uah:
            return None
        if currency == "UAH":
            return amount / eur_uah
        ccy_uah = self._uah_per(currency, date)
        if not ccy_uah:
            return None
        return amount * ccy_uah / eur_uah

    def _uah_per(self, currency, date) -> Decimal | None:
        series = self._rates.get(currency)
        if not series:
            return None
        hit = None
        for d, rate in series:
            if d > date:
                break
            hit = rate
        return hit


def summarize_eur(qs) -> dict:
    """Native per-currency breakdown plus EUR totals (converted when needed)."""
    qs = _unique(qs)
    native_rows = list(
        qs.values("currency")
        .annotate(
            count=Count("id"),
            income=Sum("amount", filter=Q(amount__gte=0)),
            expense=Sum("amount", filter=Q(amount__lt=0)),
        )
        .order_by("currency")
    )
    currencies = [
        {
            "currency": row["currency"] or "EUR",
            "count": row["count"] or 0,
            "income": row["income"] or 0,
            "expense": row["expense"] or 0,
            "net": (row["income"] or 0) + (row["expense"] or 0),
        }
        for row in native_rows
    ]
    mixed = len(currencies) > 1
    count = sum(c["count"] for c in currencies)
    needs_fx = any(c["currency"].upper() != "EUR" for c in currencies)

    def money(value):
        return float(value) if value is not None else None

    if not needs_fx:
        income = sum((c["income"] or 0) for c in currencies)
        expense = sum((c["expense"] or 0) for c in currencies)
        return {
            "count": count,
            "income": money(income),
            "expense": money(expense),
            "net": money(income + expense),
            "currency": "EUR",
            "currencies": currencies,
            "mixed": mixed,
            "converted": False,
        }

    buckets = list(
        qs.values("operation_date", "currency").annotate(
            income=Sum("amount", filter=Q(amount__gte=0)),
            expense=Sum("amount", filter=Q(amount__lt=0)),
        )
    )
    conv = Converter(
        [b["operation_date"] for b in buckets],
        [b["currency"] for b in buckets],
    )
    income = expense = _ZERO
    for b in buckets:
        inc = conv.to_eur(b["income"] or 0, b["currency"], b["operation_date"])
        exp = conv.to_eur(b["expense"] or 0, b["currency"], b["operation_date"])
        if inc is None or exp is None:
            return {
                "count": count,
                "income": None,
                "expense": None,
                "net": None,
                "currency": None,
                "currencies": currencies,
                "mixed": mixed,
                "converted": False,
            }
        income += inc
        expense += exp
    return {
        "count": count,
        "income": money(income),
        "expense": money(expense),
        "net": money(income + expense),
        "currency": "EUR",
        "currencies": currencies,
        "mixed": mixed,
        "converted": True,
    }


def period_start(day: dt.date, granularity: str) -> dt.date:
    if granularity == "day":
        return day
    if granularity == "week":
        return day - dt.timedelta(days=day.weekday())
    if granularity == "quarter":
        return day.replace(month=((day.month - 1) // 3) * 3 + 1, day=1)
    if granularity == "year":
        return day.replace(month=1, day=1)
    return day.replace(day=1)


def series_eur(qs, granularity: str) -> dict | None:
    """EUR time series. None means the caller can use SQL Trunc (all EUR)."""
    qs = _unique(qs)
    codes = sorted({(c or "EUR") for c in qs.values_list("currency", flat=True).distinct()})
    if not any(c.upper() != "EUR" for c in codes):
        return None
    buckets = list(
        qs.values("operation_date", "currency").annotate(
            income=Sum("amount", filter=Q(amount__gte=0)),
            expense=Sum("amount", filter=Q(amount__lt=0)),
            count=Count("id"),
        )
    )
    conv = Converter(
        [b["operation_date"] for b in buckets],
        [b["currency"] for b in buckets],
    )
    by_period = {}
    for b in buckets:
        day = b["operation_date"]
        if not day:
            continue
        inc = conv.to_eur(b["income"] or 0, b["currency"], day)
        exp = conv.to_eur(b["expense"] or 0, b["currency"], day)
        if inc is None or exp is None:
            return {
                "ok": False,
                "mixed": len(codes) > 1,
                "converted": False,
                "currencies": codes,
                "series": [],
            }
        rec = by_period.setdefault(
            period_start(day, granularity),
            {"income": _ZERO, "expense": _ZERO, "count": 0},
        )
        rec["income"] += inc
        rec["expense"] += exp
        rec["count"] += b["count"] or 0
    series = [
        {
            "period": dt.datetime.combine(day, dt.time.min).isoformat(),
            "income": float(rec["income"]),
            "expense": float(rec["expense"]),
            "net": float(rec["income"] + rec["expense"]),
            "count": rec["count"],
        }
        for day, rec in sorted(by_period.items())
    ]
    return {
        "ok": True,
        "mixed": len(codes) > 1,
        "converted": True,
        "currencies": codes,
        "series": series,
    }


def _ensure_rates(dates, currencies):
    start, end = min(dates), max(dates)
    lookback = start - dt.timedelta(days=10)
    needed = {"EUR"} | {c for c in currencies if c not in ("EUR", "UAH")}
    for cc in needed:
        existing = list(
            FxRate.objects.filter(currency=cc, date__lte=end)
            .order_by("date")
            .values_list("date", flat=True)
        )
        if (
            existing
            and existing[0] <= start
            and existing[-1] >= end - dt.timedelta(days=3)
        ):
            continue
        _fetch_nbu(cc, lookback, end)


def _fetch_nbu(currency: str, start: dt.date, end: dt.date):
    params = urllib.parse.urlencode(
        {
            "start": start.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
            "valcode": currency,
            "sort": "exchangedate",
            "order": "asc",
            "json": "",
        }
    )
    req = urllib.request.Request(
        f"{NBU_URL}?{params}",
        headers={"User-Agent": "income-share/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        return
    if not isinstance(payload, list):
        return
    rows = []
    for item in payload:
        raw_date = (item.get("exchangedate") or item.get("exchangedate ") or "").strip()
        try:
            day = dt.datetime.strptime(raw_date, "%d.%m.%Y").date()
        except ValueError:
            continue
        units = Decimal(str(item.get("units") or 1))
        if item.get("rate_per_unit") not in (None, ""):
            rate = Decimal(str(item["rate_per_unit"]))
        else:
            rate = Decimal(str(item.get("rate") or 0))
            if units and units != 1:
                rate = rate / units
        if not rate:
            continue
        rows.append(FxRate(date=day, currency=currency, uah_per_unit=rate))
    if rows:
        FxRate.objects.bulk_create(rows, ignore_conflicts=True)
