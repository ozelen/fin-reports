"""Spain autónomo tax estimator (IRPF modelo 130 + RETA cuota). Not AEAT filing."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Sum

from .models import Invoice, Recurrence, TaxProfile, Transaction
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
    row = Transaction.objects.filter(
        owner=user,
        amount__gte=0,
        operation_date__gte=start,
        operation_date__lte=end,
    ).exclude(metadata__has_key="transfer").aggregate(s=Sum("amount"))
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


def estimate(user, year: int | None = None, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    year = year or today.year
    start = dt.date(year, 1, 1)
    end = dt.date(year, 12, 31)
    as_of = min(today, end) if today.year == year else (end if today.year > year else start)
    profile = get_or_create_profile(user)

    recs = list(
        Recurrence.objects.filter(owner=user, is_active=True).prefetch_related("occurrences")
    )
    income_recs = [r for r in recs if r.category == Recurrence.CAT_INCOME]
    expense_recs = [
        r
        for r in recs
        if r.category != Recurrence.CAT_TAX
        and r.category != Recurrence.CAT_INCOME
        and r.amount < 0
    ]
    tax_recs = [r for r in recs if r.category == Recurrence.CAT_TAX]
    cuota_recs = [r for r in tax_recs if r.frequency == Recurrence.FREQ_MONTH]
    irpf_recs = [r for r in tax_recs if r.frequency != Recurrence.FREQ_MONTH]

    if profile.income_from == TaxProfile.INCOME_TAGS:
        ytd_income = _tagged_income(user, start, as_of)
    else:
        ytd_income = _issued_income(user, start, as_of)

    if profile.planned_income_override is not None:
        planned_income = _d(profile.planned_income_override)
    else:
        planned_income = _draft_income(user, year) + _recurrence_remaining(
            income_recs, as_of, end
        )

    ytd_expenses = _deductible_expenses(user, profile, start, as_of)
    planned_expenses = _recurrence_remaining(expense_recs, as_of, end)

    ingresos = ytd_income + planned_income
    gastos = ytd_expenses + planned_expenses
    gross_net = ingresos - gastos
    simplificada = _ZERO
    if profile.simplificada and gross_net > 0:
        simplificada = min(gross_net * _SIMPLIFICADA_RATE, _SIMPLIFICADA_CAP)
        simplificada = simplificada.quantize(_CENTS, rounding=ROUND_HALF_UP)
    rendimiento = gross_net - simplificada

    months_left = _months_left(as_of, year)
    monthly_net = (rendimiento / Decimal("12")) if year else _ZERO
    if profile.ss_mode == TaxProfile.SS_FIXED and profile.ss_cuota_override is not None:
        cuota = abs(_d(profile.ss_cuota_override))
        ss_source = "fixed"
    else:
        cuota = reta_cuota(monthly_net, year)
        ss_source = "table"
    tarifa = False
    if profile.new_autonomo_start:
        cutoff = profile.new_autonomo_start + dt.timedelta(days=31 * _TARIFA_MONTHS)
        if as_of < cutoff:
            cuota = _TARIFA_PLANA
            tarifa = True
            ss_source = "tarifa_plana"

    ss_paid = _tax_paid(cuota_recs, start, as_of)
    ss_scheduled = _recurrence_remaining(cuota_recs, as_of, end)
    ss_projected_remaining = cuota * months_left
    ss_remaining = ss_scheduled if cuota_recs else ss_projected_remaining
    ss_year = ss_paid + ss_remaining

    withholdings = (ytd_income * _d(profile.withholding_rate) / Decimal("100")).quantize(
        _CENTS, rounding=ROUND_HALF_UP
    )

    ytd_net_for_130 = ytd_income - ytd_expenses
    if profile.simplificada and ytd_net_for_130 > 0:
        ytd_simp = min(ytd_net_for_130 * _SIMPLIFICADA_RATE, _SIMPLIFICADA_CAP)
        ytd_net_for_130 -= ytd_simp.quantize(_CENTS, rounding=ROUND_HALF_UP)
    irpf_paid = _tax_paid(irpf_recs, start, as_of)
    m130_accrued = max(_ZERO, ytd_net_for_130 * _IRPF_PAYGO)
    m130_this = max(_ZERO, m130_accrued - irpf_paid - withholdings)
    m130_scheduled = _recurrence_remaining(irpf_recs, as_of, end)
    m130_projected = max(_ZERO, rendimiento * _IRPF_PAYGO)
    m130_remaining = max(_ZERO, m130_projected - irpf_paid - withholdings)

    irpf_base = max(_ZERO, rendimiento - ss_year)
    irpf_annual = apply_scale(irpf_base, _tables(year, IRPF_SCALE))
    irpf_already = irpf_paid + withholdings + m130_scheduled
    renta_remainder = irpf_annual - irpf_already

    set_aside = ss_remaining + m130_remaining + max(_ZERO, renta_remainder)

    remaining_payments = []
    for rec in tax_recs:
        for occ in remaining_dates(rec, as_of, end):
            remaining_payments.append(
                {
                    "recurrence": rec.id,
                    "name": rec.name,
                    "date": occ.isoformat(),
                    "amount": _money(abs(_d(rec.amount))),
                    "kind": "cuota" if rec.frequency == Recurrence.FREQ_MONTH else "irpf",
                }
            )
    remaining_payments.sort(key=lambda r: r["date"])

    return {
        "year": year,
        "as_of": as_of.isoformat(),
        "tables_year": year if year in IRPF_SCALE else max(IRPF_SCALE),
        "disclaimer": (
            "Estimator only — not tax advice. Uses 2026 estatal IRPF scale and RETA "
            "minimum cuota. Regional IRPF and IVA (modelo 303) are not included."
        ),
        "income": {
            "ytd": _money(ytd_income),
            "planned": _money(planned_income),
            "total": _money(ingresos),
            "source": profile.income_from,
            "override": profile.planned_income_override is not None,
        },
        "expenses": {
            "ytd": _money(ytd_expenses),
            "planned": _money(planned_expenses),
            "total": _money(gastos),
        },
        "simplificada": _money(simplificada),
        "rendimiento_neto": _money(rendimiento),
        "ss": {
            "source": ss_source,
            "monthly_cuota": _money(cuota),
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
        },
        "irpf_annual": {
            "base": _money(irpf_base),
            "gross": _money(irpf_annual),
            "already_covered": _money(irpf_already),
            "renta_remainder": _money(renta_remainder),
        },
        "set_aside": _money(max(_ZERO, set_aside)),
        "remaining_payments": remaining_payments,
        "profile_id": profile.id,
    }
