"""Spain autónomo tax estimator (IRPF modelo 130 + RETA cuota). Not AEAT filing."""
from __future__ import annotations

import calendar
import datetime as dt
import re
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q, Sum

from .fx import Converter
from .invoicing import last_day_of_month, working_days_in_month
from .models import Client, Invoice, Recurrence, TaxProfile, Transaction
from .recurrences import remaining_dates

_ZERO = Decimal("0")
_CENTS = Decimal("0.01")
_SIMPLIFICADA_RATE = Decimal("0.05")
_SIMPLIFICADA_CAP = Decimal("2000")
_IRPF_PAYGO = Decimal("0.20")
_TARIFA_PLANA = Decimal("80")
_TARIFA_MONTHS = 12

# Estatal IRPF scale 2026 (BOE general). Regional scale is out of v1.
IRPF_SCALE = {
    2026: [
        (Decimal("12450"), Decimal("0.19")),
        (Decimal("20200"), Decimal("0.24")),
        (Decimal("35200"), Decimal("0.30")),
        (Decimal("60000"), Decimal("0.37")),
        (Decimal("300000"), Decimal("0.45")),
        (None, Decimal("0.47")),
    ],
}

# RETA 2026: monthly net upper bound → minimum cuota (Orden PJC/297/2026).
RETA_MIN_CUOTA = {
    2026: [
        (Decimal("670"), Decimal("205.88")),
        (Decimal("900"), Decimal("226.47")),
        (Decimal("1166.70"), Decimal("267.65")),
        (Decimal("1300"), Decimal("299.56")),
        (Decimal("1500"), Decimal("302.65")),
        (Decimal("1700"), Decimal("302.65")),
        (Decimal("1850"), Decimal("360.29")),
        (Decimal("2030"), Decimal("380.88")),
        (Decimal("2330"), Decimal("401.47")),
        (Decimal("2760"), Decimal("427.21")),
        (Decimal("3190"), Decimal("452.94")),
        (Decimal("3620"), Decimal("478.68")),
        (Decimal("4050"), Decimal("504.41")),
        (Decimal("6000"), Decimal("545.59")),
        (None, Decimal("607.35")),
    ],
}

_CUOTA_RE = re.compile(r"r\.?\s*e\.?\s*autonomos|tgss|cotizacion\s*005", re.I)
_IRPF_RE = re.compile(r"irpf|pago\s*fraccionado|modelo\s*130", re.I)
_BIZUM_AEAT_RE = re.compile(r"bizum\s+agencia\s+tributaria", re.I)
_REFUND_RE = re.compile(r"devoluciones\s+tributarias", re.I)
_IVA_RE = re.compile(r"\biva\b", re.I)
_IRPF_YEAR_RE = re.compile(
    r"2\.0(\d{2})\s*irpf|i\.?\s*r\.?\s*p\.?\s*f\.?\s*(\d{2})\b", re.I
)
_PERIOD_RE = re.compile(r"(\d{2})/(\d{4})")
_TAX_TX_Q = (
    Q(concept__icontains="tgss")
    | Q(concept__icontains="autonomos")
    | Q(concept__icontains="irpf")
    | Q(concept__icontains="tributaria")
    | Q(concept__icontains="fraccionado")
    | Q(concept__icontains="aeat")
    | Q(counterparty__icontains="tgss")
    | Q(counterparty__icontains="autonomos")
    | Q(counterparty__icontains="irpf")
    | Q(counterparty__icontains="tributaria")
    | Q(counterparty__icontains="aeat")
)


def _money(value) -> float | None:
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(_CENTS, rounding=ROUND_HALF_UP))


def _d(value) -> Decimal:
    if value is None:
        return _ZERO
    return Decimal(str(value))


def _tables(year: int, mapping: dict):
    if year in mapping:
        return mapping[year]
    latest = max(mapping)
    return mapping[latest]


def apply_scale(amount: Decimal, brackets) -> Decimal:
    if amount <= 0:
        return _ZERO
    tax = _ZERO
    prev = _ZERO
    remaining = amount
    for upper, rate in brackets:
        width = remaining if upper is None else min(remaining, upper - prev)
        if width <= 0:
            break
        tax += width * rate
        remaining -= width
        if upper is None or remaining <= 0:
            break
        prev = upper
    return tax.quantize(_CENTS, rounding=ROUND_HALF_UP)


def reta_cuota(monthly_net: Decimal, year: int) -> Decimal:
    for upper, cuota in _tables(year, RETA_MIN_CUOTA):
        if upper is None or monthly_net <= upper:
            return cuota
    return _tables(year, RETA_MIN_CUOTA)[-1][1]


def get_or_create_profile(user) -> TaxProfile:
    profile, _ = TaxProfile.objects.get_or_create(owner=user)
    return profile


def parse_irpf_year(text: str, fallback: int) -> int:
    match = _IRPF_YEAR_RE.search(text or "")
    if not match:
        return fallback
    yy = match.group(1) or match.group(2)
    return 2000 + int(yy)


def parse_cuota_period(text: str, fallback: dt.date) -> tuple[int, int]:
    match = _PERIOD_RE.search(text or "")
    if not match:
        return fallback.year, fallback.month
    return int(match.group(2)), int(match.group(1))


def classify_payment(concept, counterparty, amount, operation_date) -> dict | None:
    """Label a bank row as RETA cuota, modelo 130, or IRPF refund. Else None."""
    blob = f"{concept or ''} {counterparty or ''}"
    amount = _d(amount)
    if amount == 0:
        return None
    if _CUOTA_RE.search(blob):
        year, month = parse_cuota_period(blob, operation_date)
        return {
            "kind": "cuota",
            "tax_year": year,
            "period_month": month,
            "amount": abs(amount),
        }
    if _REFUND_RE.search(blob):
        if _IVA_RE.search(blob) and not _IRPF_RE.search(blob):
            return None
        if not (_IRPF_RE.search(blob) or re.search(r"mod\s*:?\s*100", blob, re.I)):
            return None
        return {
            "kind": "irpf_refund",
            "tax_year": parse_irpf_year(blob, operation_date.year - 1),
            "period_month": None,
            "amount": abs(amount),
        }
    if _IRPF_RE.search(blob) or _BIZUM_AEAT_RE.search(blob):
        if amount > 0:
            return None
        return {
            "kind": "irpf",
            "tax_year": parse_irpf_year(blob, operation_date.year),
            "period_month": None,
            "amount": abs(amount),
        }
    return None


def dedupe_payments(rows: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for row in rows:
        key = (row["date"], row["kind"], row["amount"], row.get("tax_year"))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _issued_income(user, start: dt.date, end: dt.date) -> Decimal:
    row = Invoice.objects.filter(
        owner=user,
        status=Invoice.STATUS_ISSUED,
        issue_date__gte=start,
        issue_date__lte=end,
    ).aggregate(s=Sum("net_amount"))
    return _d(row["s"])


def _draft_income(user, year: int) -> Decimal:
    row = Invoice.objects.filter(
        owner=user,
        status=Invoice.STATUS_DRAFT,
        service_year=year,
    ).aggregate(s=Sum("net_amount"))
    return _d(row["s"])


def _tagged_income(user, start: dt.date, end: dt.date) -> Decimal:
    row = (
        Transaction.objects.filter(
            owner=user,
            amount__gte=0,
            operation_date__gte=start,
            operation_date__lte=end,
        )
        .exclude(metadata__has_key="transfer")
        .exclude(_TAX_TX_Q)
        .aggregate(s=Sum("amount"))
    )
    return _d(row["s"])


def _deductible_expenses(user, profile: TaxProfile, start: dt.date, end: dt.date) -> Decimal:
    tags = list(profile.deductible_tags.values_list("id", flat=True))
    if not tags:
        return _ZERO
    qs = Transaction.objects.filter(
        owner=user,
        amount__lt=0,
        operation_date__gte=start,
        operation_date__lte=end,
        tags__id__in=tags,
    ).exclude(recurrence__category=Recurrence.CAT_TAX)
    row = qs.distinct().aggregate(s=Sum("amount"))
    return abs(_d(row["s"]))


def _recurrence_remaining(recs, after: dt.date, until: dt.date) -> Decimal:
    total = _ZERO
    for rec in recs:
        n = len(remaining_dates(rec, after, until))
        total += abs(_d(rec.amount)) * n
    return total


def _tax_paid(recs, start: dt.date, end: dt.date) -> Decimal:
    ids = [r.id for r in recs]
    if not ids:
        return _ZERO
    row = Transaction.objects.filter(
        recurrence_id__in=ids,
        operation_date__gte=start,
        operation_date__lte=end,
    ).aggregate(s=Sum("amount"))
    return abs(_d(row["s"]))


def _months_left(today: dt.date, year: int) -> int:
    if today.year != year:
        return 12 if today.year < year else 0
    return 12 - today.month + 1


_QUARTER_MONTHS = ((1, 1, 3), (2, 4, 6), (3, 7, 9), (4, 10, 12))


def m130_due(year: int, quarter: int) -> dt.date:
    if quarter == 4:
        return dt.date(year + 1, 1, 20)
    return dt.date(year, {1: 4, 2: 7, 3: 10}[quarter], 20)


def _deductible_recurrences(recs, tag_ids: set[int]) -> list:
    if not tag_ids:
        return []
    return [
        rec
        for rec in recs
        if rec.category != Recurrence.CAT_TAX
        and rec.amount < 0
        and tag_ids & {t.id for t in rec.tags.all()}
    ]


def _quarter_gastos(user, profile, year, start_m, end_m, today, deduct_recs) -> Decimal:
    start = dt.date(year, start_m, 1)
    last = calendar.monthrange(year, end_m)[1]
    end = dt.date(year, end_m, last)
    as_of = min(today, end) if today.year == year else (end if today.year > year else start)
    actual = _deductible_expenses(user, profile, start, as_of)
    planned = _ZERO
    if as_of < end:
        planned = _recurrence_remaining(deduct_recs, as_of, end)
    return actual + planned


def modelo_130_quarters(
    *,
    year: int,
    months: list[dict],
    ss_by_month: dict,
    gastos_by_quarter: dict | None = None,
    paid: list,
    today: dt.date,
    default_cuota: Decimal,
) -> list[dict]:
    """Q1–Q4: actual paid installments, then 20% of each remaining quarter's net."""
    income_by = {int(row["month"]): _d(row["amount"]) for row in months}
    paid = [_d(x) for x in paid]
    gastos_by_quarter = gastos_by_quarter or {}
    rows = []
    for i, (q, start_m, end_m) in enumerate(_QUARTER_MONTHS):
        due = m130_due(year, q)
        income = sum((income_by.get(m, _ZERO) for m in range(start_m, end_m + 1)), _ZERO)
        ss = sum(
            (_d(ss_by_month.get(m, default_cuota)) for m in range(start_m, end_m + 1)),
            _ZERO,
        )
        gastos = _d(gastos_by_quarter.get(q))
        computed = max(_ZERO, (income - ss - gastos) * _IRPF_PAYGO).quantize(
            _CENTS, rounding=ROUND_HALF_UP
        )
        last = calendar.monthrange(year, end_m)[1]
        ended = today > dt.date(year, end_m, last)
        if i < len(paid):
            amount, status = paid[i], "paid"
        else:
            amount = computed
            status = "due" if ended else "forecast"
        rows.append(
            {
                "quarter": q,
                "start_month": start_m,
                "end_month": end_m,
                "due": due,
                "income": income,
                "ss": ss,
                "gastos": gastos,
                "amount": amount,
                "status": status,
            }
        )
    return rows


def irpf_schedule_name(year: int, quarter: int) -> str:
    return f"IRPF Pago Fraccionado {year} Q{quarter}"


def sync_irpf_recurrences(user, year: int, quarters: list[dict]) -> dict[int, int]:
    """Upsert one quarterly recurrence per unpaid 130. Deactivate once paid."""
    tgss = (
        Recurrence.objects.filter(
            owner=user, category=Recurrence.CAT_TAX, frequency=Recurrence.FREQ_MONTH
        )
        .order_by("id")
        .first()
    )
    account_id = tgss.account_id if tgss else None
    prefix = f"IRPF Pago Fraccionado {year} Q"
    existing = {
        rec.name: rec
        for rec in Recurrence.objects.filter(owner=user, name__startswith=prefix)
    }
    ids = {}
    for row in quarters:
        name = irpf_schedule_name(year, row["quarter"])
        rec = existing.get(name)
        amount = -_d(row["amount"])
        due = row["due"]
        if row["status"] == "paid":
            if rec and rec.is_active:
                rec.amount = amount
                rec.is_active = False
                rec.save(update_fields=["amount", "is_active"])
            if rec:
                ids[row["quarter"]] = rec.id
            continue
        fields = {
            "amount": amount,
            "currency": "EUR",
            "frequency": Recurrence.FREQ_QUARTER,
            "due_day": 20,
            "start_date": due,
            "end_date": due,
            "match_text": "Irpf. Pago Fraccionado",
            "amount_tolerance_pct": Decimal("100"),
            "auto_match": True,
            "category": Recurrence.CAT_TAX,
            "is_active": True,
            "account_id": account_id,
        }
        if rec:
            for key, value in fields.items():
                setattr(rec, key, value)
            rec.save()
        else:
            rec = Recurrence.objects.create(owner=user, name=name, **fields)
        ids[row["quarter"]] = rec.id
    return ids


def _load_bank_tax(user) -> list[dict]:
    rows = []
    qs = Transaction.objects.filter(owner=user).filter(_TAX_TX_Q).order_by(
        "operation_date", "id"
    )
    for tx in qs:
        hit = classify_payment(tx.concept, tx.counterparty, tx.amount, tx.operation_date)
        if not hit:
            continue
        rows.append(
            {
                **hit,
                "id": tx.id,
                "date": tx.operation_date.isoformat(),
                "label": (tx.counterparty or tx.concept)[:80],
            }
        )
    return dedupe_payments(rows)


def _invoice_months(user, year: int) -> dict[int, tuple[Decimal, Decimal]]:
    """service_month → (hours, net). Used when no clients are in scope."""
    out: dict[int, tuple[Decimal, Decimal]] = {}
    qs = Invoice.objects.filter(owner=user, service_year=year).exclude(
        status=Invoice.STATUS_DRAFT
    )
    for inv in qs:
        hours, net = out.get(inv.service_month, (_ZERO, _ZERO))
        out[inv.service_month] = (hours + _d(inv.quantity), net + _d(inv.net_amount))
    drafts = Invoice.objects.filter(
        owner=user, service_year=year, status=Invoice.STATUS_DRAFT
    )
    for inv in drafts:
        if inv.service_month in out:
            continue
        out[inv.service_month] = (_d(inv.quantity), _d(inv.net_amount))
    return out


def engagement_overlaps(client, start: dt.date, end: dt.date) -> bool:
    if client.active_from and client.active_from > end:
        return False
    if client.active_to and client.active_to < start:
        return False
    return True


def client_engaged(client, year: int, month: int) -> bool:
    start = dt.date(year, month, 1)
    end = last_day_of_month(year, month)
    return engagement_overlaps(client, start, end)


def _to_eur(conv: Converter | None, amount, currency, day) -> Decimal:
    amount = _d(amount)
    currency = (currency or "EUR").upper()
    if not amount or currency == "EUR" or conv is None:
        return amount
    eur = conv.to_eur(amount, currency, day)
    return _d(eur) if eur is not None else amount


def clients_for_year(user, year: int, today: dt.date | None = None) -> list[Client]:
    today = today or dt.date.today()
    year_start = dt.date(year, 1, 1)
    year_end = dt.date(year, 12, 31)
    invoice_ids = set(
        Invoice.objects.filter(owner=user, service_year=year).values_list(
            "client_id", flat=True
        )
    )
    tx_ids = set(
        Transaction.objects.filter(
            owner=user,
            client_id__isnull=False,
            amount__gt=0,
            operation_date__gte=year_start,
            operation_date__lte=year_end,
        ).values_list("client_id", flat=True)
    )
    record_ids = {i for i in invoice_ids | tx_ids if i}
    rows = []
    for client in Client.objects.filter(owner=user):
        if client.id in record_ids:
            rows.append(client)
            continue
        if not _d(client.default_unit_price):
            continue
        if not engagement_overlaps(client, year_start, year_end):
            continue
        if client.active_from or client.active_to or year >= today.year:
            rows.append(client)
    rows.sort(key=lambda c: ((c.short_name or c.name).lower(), c.id))
    return rows


def _invoice_by_client(user, year: int, conv: Converter | None) -> dict:
    """(client_id, month) → (quantity, net_eur). Issued wins; draft fills gaps."""
    out: dict[tuple[int, int], tuple[Decimal, Decimal]] = {}
    issued = Invoice.objects.filter(owner=user, service_year=year).exclude(
        status=Invoice.STATUS_DRAFT
    )
    for inv in issued:
        day = inv.sale_date or last_day_of_month(year, inv.service_month)
        eur = _to_eur(conv, inv.net_amount, inv.currency, day)
        key = (inv.client_id, inv.service_month)
        qty, net = out.get(key, (_ZERO, _ZERO))
        out[key] = (qty + _d(inv.quantity), net + eur)
    drafts = Invoice.objects.filter(
        owner=user, service_year=year, status=Invoice.STATUS_DRAFT
    )
    for inv in drafts:
        key = (inv.client_id, inv.service_month)
        if key in out:
            continue
        day = inv.sale_date or last_day_of_month(year, inv.service_month)
        out[key] = (
            _d(inv.quantity),
            _to_eur(conv, inv.net_amount, inv.currency, day),
        )
    return out


def _bank_by_client(user, year: int, conv: Converter | None) -> dict:
    start = dt.date(year, 1, 1)
    end = dt.date(year, 12, 31)
    out: dict[tuple[int, int], Decimal] = {}
    qs = Transaction.objects.filter(
        owner=user,
        client_id__isnull=False,
        amount__gt=0,
        operation_date__gte=start,
        operation_date__lte=end,
    )
    for tx in qs:
        eur = _to_eur(conv, tx.amount, tx.currency, tx.operation_date)
        key = (tx.client_id, tx.operation_date.month)
        out[key] = out.get(key, _ZERO) + eur
    return out


def calendar_amount(
    client,
    *,
    days: int,
    hours_per_day: int,
    hours_override,
    conv: Converter | None,
    fx_date: dt.date,
) -> tuple[Decimal, Decimal, str]:
    """Return (quantity, eur_amount, source). Quantity is hours or days."""
    rate = _to_eur(conv, client.default_unit_price, client.currency, fx_date)
    if client.billing_unit == Client.UNIT_DAY:
        qty = Decimal(days)
        amount = (qty * rate).quantize(_CENTS, rounding=ROUND_HALF_UP)
        return qty, amount, "calendar"
    if hours_override not in (None, ""):
        qty = _d(hours_override)
        amount = (qty * rate).quantize(_CENTS, rounding=ROUND_HALF_UP)
        return qty, amount, "override"
    qty = Decimal(days * hours_per_day)
    amount = (qty * rate).quantize(_CENTS, rounding=ROUND_HALF_UP)
    return qty, amount, "calendar"


def month_hours_plan(profile: TaxProfile, year: int, invoices: dict) -> list[dict]:
    rate = _d(profile.hourly_rate) or Decimal("30")
    hpd = int(profile.hours_per_day or 8)
    overrides = profile.hours_overrides or {}
    rows = []
    for month in range(1, 13):
        days = working_days_in_month(year, month)
        calendar_hours = Decimal(days * hpd)
        key = f"{year}-{month:02d}"
        inv = invoices.get(month)
        if key in overrides and overrides[key] not in (None, ""):
            hours = _d(overrides[key])
            source = "override"
            amount = (hours * rate).quantize(_CENTS, rounding=ROUND_HALF_UP)
        elif inv is not None:
            hours, amount = inv
            source = "invoice"
        else:
            hours = calendar_hours
            source = "calendar"
            amount = (hours * rate).quantize(_CENTS, rounding=ROUND_HALF_UP)
        rows.append(
            {
                "month": month,
                "key": key,
                "working_days": days,
                "calendar_hours": _money(calendar_hours),
                "invoice_hours": _money(inv[0]) if inv else None,
                "hours": _money(hours),
                "amount": _money(amount),
                "source": source,
                "by_client": {},
            }
        )
    return rows


def month_client_plan(
    profile: TaxProfile,
    year: int,
    clients: list,
    invoices: dict,
    bank: dict,
    conv: Converter | None = None,
    today: dt.date | None = None,
) -> list[dict]:
    today = today or dt.date.today()
    hpd = int(profile.hours_per_day or 8)
    overrides = profile.hours_overrides or {}
    rows = []
    for month in range(1, 13):
        days = working_days_in_month(year, month)
        calendar_hours = Decimal(days * hpd)
        key = f"{year}-{month:02d}"
        fx_date = last_day_of_month(year, month)
        override = overrides.get(key)
        by_client = {}
        total = _ZERO
        hours = calendar_hours
        sources = []
        invoice_hours = _ZERO
        has_invoice_hours = False
        for client in clients:
            inv = invoices.get((client.id, month))
            paid = bank.get((client.id, month))
            engaged = client_engaged(client, year, month)
            client_days = working_days_in_month(
                year,
                month,
                start=getattr(client, "active_from", None),
                end=getattr(client, "active_to", None),
            )
            if override not in (None, "") and engaged and client.billing_unit != Client.UNIT_DAY:
                qty, amount, source = calendar_amount(
                    client,
                    days=client_days,
                    hours_per_day=hpd,
                    hours_override=override,
                    conv=conv,
                    fx_date=fx_date,
                )
                hours = qty
            elif inv is not None:
                qty, amount = inv
                source = "invoice"
                invoice_hours += qty
                has_invoice_hours = True
            elif paid is not None:
                qty = calendar_hours
                amount = paid.quantize(_CENTS, rounding=ROUND_HALF_UP)
                source = "bank"
            elif (
                engaged
                and _d(client.default_unit_price)
                and (year, month) >= (today.year, today.month)
            ):
                qty, amount, source = calendar_amount(
                    client,
                    days=client_days,
                    hours_per_day=hpd,
                    hours_override=None,
                    conv=conv,
                    fx_date=fx_date,
                )
            else:
                qty, amount, source = _ZERO, _ZERO, ""
            if source:
                sources.append(source)
            by_client[str(client.id)] = {
                "amount": _money(amount),
                "source": source or None,
                "quantity": _money(qty) if source else None,
            }
            total += amount
        source = sources[0] if len(set(sources)) == 1 else ("mixed" if sources else "calendar")
        rows.append(
            {
                "month": month,
                "key": key,
                "working_days": days,
                "calendar_hours": _money(calendar_hours),
                "invoice_hours": _money(invoice_hours) if has_invoice_hours else None,
                "hours": _money(hours),
                "amount": _money(total),
                "source": source,
                "by_client": by_client,
            }
        )
    return rows


def estimate(user, year: int | None = None, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    year = year or today.year
    start = dt.date(year, 1, 1)
    end = dt.date(year, 12, 31)
    as_of = min(today, end) if today.year == year else (end if today.year > year else start)
    profile = get_or_create_profile(user)

    recs = list(
        Recurrence.objects.filter(owner=user, is_active=True).prefetch_related(
            "occurrences", "tags"
        )
    )
    income_recs = [r for r in recs if r.category == Recurrence.CAT_INCOME]
    deduct_ids = set(profile.deductible_tags.values_list("id", flat=True))
    deduct_recs = _deductible_recurrences(recs, deduct_ids)
    tax_recs = [r for r in recs if r.category == Recurrence.CAT_TAX]
    cuota_recs = [r for r in tax_recs if r.frequency == Recurrence.FREQ_MONTH]
    irpf_recs = [r for r in tax_recs if r.frequency != Recurrence.FREQ_MONTH]

    year_clients = clients_for_year(user, year, today)
    conv = Converter(
        [last_day_of_month(year, m) for m in range(1, 13)],
        {c.currency for c in year_clients} | {"EUR"},
    )
    if year_clients:
        invoices = _invoice_by_client(user, year, conv)
        bank = _bank_by_client(user, year, conv)
        months = month_client_plan(
            profile, year, year_clients, invoices, bank, conv, today
        )
    else:
        invoices = _invoice_months(user, year)
        months = month_hours_plan(profile, year, invoices)
    hours_ytd = _ZERO
    hours_planned = _ZERO
    for row in months:
        amt = _d(row["amount"])
        if today.year > year:
            done = True
        elif today.year < year:
            done = False
        else:
            done = row["month"] < today.month or (
                row["month"] == today.month and row["source"] == "invoice"
            )
        if done:
            hours_ytd += amt
            row["bucket"] = "ytd"
        else:
            hours_planned += amt
            row["bucket"] = "planned"

    if profile.income_from == TaxProfile.INCOME_TAGS:
        ytd_income = _tagged_income(user, start, as_of)
        planned_income = hours_planned
        income_source = "tags"
    elif profile.income_from == TaxProfile.INCOME_INVOICES:
        ytd_income = _issued_income(user, start, as_of)
        planned_income = _draft_income(user, year) + _recurrence_remaining(
            income_recs, as_of, end
        )
        income_source = "invoices"
    else:
        ytd_income = hours_ytd
        planned_income = hours_planned
        income_source = "hours"

    if profile.planned_income_override is not None:
        planned_income = _d(profile.planned_income_override)

    ytd_expenses = _deductible_expenses(user, profile, start, as_of)
    planned_expenses = _recurrence_remaining(deduct_recs, as_of, end)

    bank_tax = [p for p in _load_bank_tax(user) if p["tax_year"] == year]
    cuota_paid_rows = [p for p in bank_tax if p["kind"] == "cuota"]
    irpf_paid_rows = [p for p in bank_tax if p["kind"] == "irpf"]
    irpf_refund_rows = [p for p in bank_tax if p["kind"] == "irpf_refund"]

    ss_paid = sum((_d(p["amount"]) for p in cuota_paid_rows), _ZERO)
    if not cuota_paid_rows:
        ss_paid = _tax_paid(cuota_recs, start, as_of)

    irpf_paid = sum((_d(p["amount"]) for p in irpf_paid_rows), _ZERO)
    irpf_paid -= sum((_d(p["amount"]) for p in irpf_refund_rows), _ZERO)
    if not irpf_paid_rows and not irpf_refund_rows:
        irpf_paid = _tax_paid(irpf_recs, start, as_of)

    paid_cuota_months = {p["period_month"] for p in cuota_paid_rows if p.get("period_month")}
    if today.year > year:
        unpaid_cuota_months = []
    elif today.year < year:
        unpaid_cuota_months = list(range(1, 13))
    else:
        unpaid_cuota_months = [
            m for m in range(today.month, 13) if m not in paid_cuota_months
        ]
    months_left = _months_left(as_of, year)

    ingresos = ytd_income + planned_income
    last_cuota = _d(cuota_paid_rows[-1]["amount"]) if cuota_paid_rows else _ZERO
    table_cuota = reta_cuota((ingresos / Decimal("12")) if ingresos else _ZERO, year)

    if profile.ss_mode == TaxProfile.SS_FIXED and profile.ss_cuota_override is not None:
        cuota = abs(_d(profile.ss_cuota_override))
        ss_source = "fixed"
    elif last_cuota:
        cuota = last_cuota
        ss_source = "last_paid"
    else:
        cuota = table_cuota
        ss_source = "table"
    tarifa = False
    if profile.new_autonomo_start:
        cutoff = profile.new_autonomo_start + dt.timedelta(days=31 * _TARIFA_MONTHS)
        if as_of < cutoff:
            cuota = _TARIFA_PLANA
            tarifa = True
            ss_source = "tarifa_plana"

    if cuota_paid_rows:
        ss_remaining = cuota * Decimal(len(unpaid_cuota_months))
    elif cuota_recs:
        ss_remaining = _recurrence_remaining(cuota_recs, as_of, end)
    else:
        ss_remaining = cuota * Decimal(months_left)
    ss_year = ss_paid + ss_remaining

    # SS cuota is a deductible gasto for modelo 130.
    gastos = ytd_expenses + planned_expenses + ss_year
    gross_net = ingresos - gastos
    simplificada = _ZERO
    if profile.simplificada and gross_net > 0:
        simplificada = min(gross_net * _SIMPLIFICADA_RATE, _SIMPLIFICADA_CAP)
        simplificada = simplificada.quantize(_CENTS, rounding=ROUND_HALF_UP)
    rendimiento = gross_net - simplificada

    ss_by_month = {
        p["period_month"]: _d(p["amount"])
        for p in cuota_paid_rows
        if p.get("period_month")
    }
    gastos_by_quarter = {
        q: _quarter_gastos(user, profile, year, start_m, end_m, today, deduct_recs)
        for q, start_m, end_m in _QUARTER_MONTHS
    }
    quarters = modelo_130_quarters(
        year=year,
        months=months,
        ss_by_month=ss_by_month,
        gastos_by_quarter=gastos_by_quarter,
        paid=[p["amount"] for p in irpf_paid_rows],
        today=today,
        default_cuota=cuota,
    )
    rec_ids = sync_irpf_recurrences(user, year, quarters)
    unpaid_130 = [q for q in quarters if q["status"] != "paid"]
    m130_this = unpaid_130[0]["amount"] if unpaid_130 else _ZERO
    m130_remaining = sum((q["amount"] for q in unpaid_130), _ZERO)
    m130_scheduled = m130_remaining

    withholdings = (ytd_income * _d(profile.withholding_rate) / Decimal("100")).quantize(
        _CENTS, rounding=ROUND_HALF_UP
    )

    irpf_base = max(_ZERO, rendimiento)
    irpf_annual = apply_scale(irpf_base, _tables(year, IRPF_SCALE))
    irpf_already = irpf_paid + withholdings + m130_scheduled
    renta_remainder = irpf_annual - irpf_already

    set_aside = ss_remaining + m130_remaining

    remaining_payments = []
    for month in unpaid_cuota_months:
        last = calendar.monthrange(year, month)[1]
        remaining_payments.append(
            {
                "recurrence": None,
                "name": "RETA cuota",
                "date": dt.date(year, month, last).isoformat(),
                "amount": _money(cuota),
                "kind": "cuota",
            }
        )
    for q in unpaid_130:
        remaining_payments.append(
            {
                "recurrence": rec_ids.get(q["quarter"]),
                "name": irpf_schedule_name(year, q["quarter"]),
                "date": q["due"].isoformat(),
                "amount": _money(q["amount"]),
                "kind": "irpf",
                "status": q["status"],
            }
        )
    remaining_payments.sort(key=lambda r: r["date"])

    return {
        "year": year,
        "as_of": as_of.isoformat(),
        "tables_year": year if year in IRPF_SCALE else max(IRPF_SCALE),
        "disclaimer": (
            "Estimator only — not tax advice. Uses 2026 estatal IRPF scale and RETA "
            "minimum cuota. Regional IRPF and IVA (modelo 303) are not included. "
            "Duplicate bank imports are counted once."
        ),
        "income": {
            "ytd": _money(ytd_income),
            "planned": _money(planned_income),
            "total": _money(ingresos),
            "source": income_source,
            "override": profile.planned_income_override is not None,
            "hourly_rate": _money(_d(profile.hourly_rate) or Decimal("30")),
            "hours_per_day": int(profile.hours_per_day or 8),
        },
        "clients": [
            {
                "id": c.id,
                "name": c.name,
                "short_name": c.display_name(),
                "billing_unit": c.billing_unit or Client.UNIT_HOUR,
                "currency": c.currency,
                "unit_price": _money(c.default_unit_price),
            }
            for c in year_clients
        ],
        "expenses": {
            "ytd": _money(ytd_expenses),
            "planned": _money(planned_expenses),
            "ss": _money(ss_year),
            "total": _money(gastos),
        },
        "simplificada": _money(simplificada),
        "rendimiento_neto": _money(rendimiento),
        "ss": {
            "source": ss_source,
            "monthly_cuota": _money(cuota),
            "statutory_min": _money(table_cuota),
            "tarifa_plana": tarifa,
            "paid": _money(ss_paid),
            "remaining": _money(ss_remaining),
            "year_total": _money(ss_year),
        },
        "modelo_130": {
            "rate": float(_IRPF_PAYGO),
            "this_installment": _money(m130_this),
            "paid": _money(irpf_paid),
            "withholdings": _money(withholdings),
            "scheduled": _money(m130_scheduled),
            "remaining": _money(m130_remaining),
            "quarters": [
                {
                    "quarter": q["quarter"],
                    "period": f"{q['start_month']:02d}–{q['end_month']:02d}",
                    "due": q["due"].isoformat(),
                    "income": _money(q["income"]),
                    "ss": _money(q["ss"]),
                    "gastos": _money(q["gastos"]),
                    "amount": _money(q["amount"]),
                    "status": q["status"],
                    "recurrence": rec_ids.get(q["quarter"]),
                }
                for q in quarters
            ],
        },
        "irpf_annual": {
            "base": _money(irpf_base),
            "gross": _money(irpf_annual),
            "already_covered": _money(irpf_already),
            "renta_remainder": _money(renta_remainder),
        },
        "set_aside": _money(max(_ZERO, set_aside)),
        "months": months,
        "paid_payments": [
            {
                "id": p["id"],
                "date": p["date"],
                "name": p["label"],
                "kind": p["kind"],
                "amount": _money(p["amount"] if p["kind"] != "irpf_refund" else -p["amount"]),
            }
            for p in bank_tax
        ],
        "remaining_payments": remaining_payments,
        "profile_id": profile.id,
    }
