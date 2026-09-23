"""Classify autónomo bank payments and Mon–Fri hour forecasts."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase

from core.budgets import irpf_monthly_in_window, rec_planned
from core.invoicing import advise_hours, working_days_in_month
from core.models import Client
from core.tax import (
    calendar_amount,
    classify_payment,
    dedupe_payments,
    m130_due,
    modelo_130_quarters,
    month_client_plan,
    month_hours_plan,
    parse_cuota_period,
    parse_irpf_year,
)


class ClassifyPaymentTests(TestCase):
    def test_tgss_cuota_reads_liquidation_period(self):
        hit = classify_payment(
            "RECIBO TGSS. COTIZACION 005 R.E.AUTONOMOS, concepto: PERIODO LIQUIDACION: 07/2026-07/2026",
            "TGSS. COTIZACION 005 R.E.AUTONOMOS",
            Decimal("-299.57"),
            date(2026, 7, 31),
        )
        self.assertEqual(hit["kind"], "cuota")
        self.assertEqual(hit["tax_year"], 2026)
        self.assertEqual(hit["period_month"], 7)
        self.assertEqual(hit["amount"], Decimal("299.57"))

    def test_irpf_year_from_concepto_not_payment_date(self):
        hit = classify_payment(
            "Domiciliacion Impuesto: 2.025 Irpf. Pago Fraccionado",
            "Impuesto: 2.025 Irpf. Pago Fraccionado",
            Decimal("-1197.76"),
            date(2026, 1, 30),
        )
        self.assertEqual(hit["kind"], "irpf")
        self.assertEqual(hit["tax_year"], 2025)
        self.assertEqual(hit["amount"], Decimal("1197.76"))

    def test_bizum_agencia_tributaria_is_irpf(self):
        hit = classify_payment(
            "Compra Bizum Agencia Tributaria 16/07/2026",
            "Bizum Agencia Tributaria 16/07/",
            Decimal("-2097.55"),
            date(2026, 7, 16),
        )
        self.assertEqual(hit["kind"], "irpf")
        self.assertEqual(hit["tax_year"], 2026)

    def test_personal_bizum_is_ignored(self):
        self.assertIsNone(
            classify_payment(
                "Bizum A Favor De Zoryana Zelenyuk Concepto: Sin Concepto",
                "Zoryana Zelenyuk",
                Decimal("-1000"),
                date(2026, 1, 16),
            )
        )

    def test_irpf_refund_year_from_mod_100(self):
        hit = classify_payment(
            "Transferencia De Devoluciones Tributarias, Agencia Estatal De Admin, Concepto Aeat Apl:declaracion I.r.p.f 24mod:100inf:expediente",
            "Devoluciones Tributarias, Agencia Estatal De Admin",
            Decimal("3563.90"),
            date(2025, 6, 13),
        )
        self.assertEqual(hit["kind"], "irpf_refund")
        self.assertEqual(hit["tax_year"], 2024)

    def test_iva_refund_is_ignored(self):
        self.assertIsNone(
            classify_payment(
                "TRANSFERENCIA DE DEVOLUCIONES TRIBUTARIAS, AGENCIA ESTATAL DE ADMIN, CONCEPTO AEAT APL:IVA AUTOLIQUI",
                "DEVOLUCIONES TRIBUTARIAS, AGENCIA ESTATAL DE ADMIN",
                Decimal("1087.06"),
                date(2026, 8, 4),
            )
        )

    def test_parse_helpers(self):
        self.assertEqual(parse_irpf_year("Impuesto: 2.026 Irpf", 2026), 2026)
        self.assertEqual(parse_cuota_period("PERIODO LIQUIDACION: 04/2026-04/2026", date(2026, 4, 30)), (2026, 4))

    def test_duplicate_bank_rows_count_once(self):
        rows = [
            {"date": "2026-07-16", "kind": "irpf", "amount": Decimal("2097.55"), "tax_year": 2026},
            {"date": "2026-07-16", "kind": "irpf", "amount": Decimal("2097.55"), "tax_year": 2026},
        ]
        self.assertEqual(len(dedupe_payments(rows)), 1)


class HoursPlanTests(TestCase):
    def test_july_2026_is_184_hours(self):
        self.assertEqual(working_days_in_month(2026, 7), 23)
        self.assertEqual(working_days_in_month(2026, 9), 22)
        self.assertEqual(
            working_days_in_month(2026, 9, start=date(2026, 9, 21)), 8
        )
        self.assertEqual(
            working_days_in_month(
                2027, 3, start=date(2026, 9, 21), end=date(2027, 3, 20)
            ),
            15,
        )
        profile = SimpleNamespace(
            hourly_rate=Decimal("30"),
            hours_per_day=8,
            hours_overrides={},
        )
        july = month_hours_plan(profile, 2026, {})[6]
        self.assertEqual(july["hours"], 184.0)
        self.assertEqual(july["amount"], 5520.0)
        self.assertEqual(july["source"], "calendar")

    def test_override_and_invoice_win(self):
        profile = SimpleNamespace(
            hourly_rate=Decimal("30"),
            hours_per_day=8,
            hours_overrides={"2026-08": 152},
        )
        invoices = {7: (Decimal("184"), Decimal("5520"))}
        rows = month_hours_plan(profile, 2026, invoices)
        self.assertEqual(rows[6]["source"], "invoice")
        self.assertEqual(rows[6]["amount"], 5520.0)
        self.assertEqual(rows[7]["source"], "override")
        self.assertEqual(rows[7]["hours"], 152.0)
        self.assertEqual(rows[7]["amount"], 4560.0)


class ClientPlanTests(TestCase):
    def test_day_rate_uses_working_days(self):
        client = SimpleNamespace(
            id=2,
            billing_unit=Client.UNIT_DAY,
            default_unit_price=Decimal("400"),
            currency="EUR",
        )
        qty, amount, source = calendar_amount(
            client,
            days=23,
            hours_per_day=8,
            hours_override=None,
            conv=None,
            fx_date=date(2026, 7, 31),
        )
        self.assertEqual(source, "calendar")
        self.assertEqual(qty, Decimal("23"))
        self.assertEqual(amount, Decimal("9200.00"))

    def test_day_rate_clips_to_contract_start(self):
        client = SimpleNamespace(
            id=6,
            billing_unit=Client.UNIT_DAY,
            default_unit_price=Decimal("410"),
            currency="EUR",
            active_from=date(2026, 9, 21),
            active_to=date(2027, 3, 20),
        )
        profile = SimpleNamespace(hours_per_day=8, hours_overrides={})
        rows = month_client_plan(
            profile,
            2026,
            [client],
            invoices={},
            bank={},
            conv=None,
            today=date(2026, 9, 23),
        )
        sep = rows[8]
        self.assertEqual(sep["by_client"]["6"]["source"], "calendar")
        self.assertEqual(sep["by_client"]["6"]["quantity"], 8.0)
        self.assertEqual(sep["by_client"]["6"]["amount"], 3280.0)
        advice = advise_hours(
            2026,
            9,
            unit=Client.UNIT_DAY,
            start=date(2026, 9, 21),
            end=date(2027, 3, 20),
        )
        self.assertEqual(advice["working_days"], 8)
        self.assertEqual(advice["suggested_quantity"], 8)

    def test_columns_mix_invoice_bank_and_calendar(self):
        profile = SimpleNamespace(hours_per_day=8, hours_overrides={})
        netguru = SimpleNamespace(
            id=1,
            billing_unit=Client.UNIT_HOUR,
            default_unit_price=Decimal("30"),
            currency="EUR",
            active_from=date(2026, 4, 1),
            active_to=None,
        )
        pinup = SimpleNamespace(
            id=2,
            billing_unit=Client.UNIT_HOUR,
            default_unit_price=Decimal("50"),
            currency="EUR",
            active_from=date(2025, 2, 1),
            active_to=date(2025, 5, 31),
        )
        rows = month_client_plan(
            profile,
            2026,
            [netguru, pinup],
            invoices={(1, 7): (Decimal("184"), Decimal("5520"))},
            bank={(1, 6): Decimal("4800")},
            conv=None,
        )
        june = rows[5]
        july = rows[6]
        jan = rows[0]
        self.assertEqual(june["by_client"]["1"]["source"], "bank")
        self.assertEqual(june["by_client"]["1"]["amount"], 4800.0)
        self.assertEqual(july["by_client"]["1"]["source"], "invoice")
        self.assertEqual(july["amount"], 5520.0)
        self.assertIsNone(jan["by_client"]["1"]["source"])
        self.assertIsNone(jan["by_client"]["2"]["source"])
        self.assertEqual(jan["amount"], 0.0)


class Modelo130QuarterTests(TestCase):
    def test_paid_quarters_keep_bank_amount_future_is_20_percent(self):
        months = [{"month": m, "amount": Decimal("5000")} for m in range(1, 13)]
        ss = {m: Decimal("300") for m in range(1, 13)}
        paid = [Decimal("1051.93"), Decimal("2097.55")]
        rows = modelo_130_quarters(
            year=2026,
            months=months,
            ss_by_month=ss,
            paid=paid,
            today=date(2026, 8, 21),
            default_cuota=Decimal("300"),
        )
        self.assertEqual(m130_due(2026, 3), date(2026, 10, 20))
        self.assertEqual(m130_due(2026, 4), date(2027, 1, 20))
        self.assertEqual(rows[0]["status"], "paid")
        self.assertEqual(rows[0]["amount"], Decimal("1051.93"))
        self.assertEqual(rows[1]["status"], "paid")
        self.assertEqual(rows[1]["amount"], Decimal("2097.55"))
        # Q3 Jul–Sep: 3×5000 − 3×300 = 14100 × 20% = 2820, due 20 Oct (forecast)
        self.assertEqual(rows[2]["status"], "forecast")
        self.assertEqual(rows[2]["amount"], Decimal("2820.00"))
        self.assertEqual(rows[2]["due"], date(2026, 10, 20))
        self.assertEqual(rows[3]["due"], date(2027, 1, 20))
        self.assertEqual(rows[3]["amount"], Decimal("2820.00"))

    def test_gastos_cut_the_installment_by_20_percent(self):
        months = [{"month": m, "amount": Decimal("5000")} for m in range(1, 13)]
        rows = modelo_130_quarters(
            year=2026,
            months=months,
            ss_by_month={},
            gastos_by_quarter={3: Decimal("1000")},
            paid=[Decimal("1"), Decimal("1")],
            today=date(2026, 8, 21),
            default_cuota=Decimal("0"),
        )
        # Q3: 15000 − 1000 gastos = 14000 × 20% = 2800
        self.assertEqual(rows[2]["gastos"], Decimal("1000"))
        self.assertEqual(rows[2]["amount"], Decimal("2800.00"))


def _irpf(name, amount, due):
    return SimpleNamespace(
        is_active=True,
        category="tax",
        name=name,
        amount=amount,
        start_date=due,
    )


class IrpfMonthlyBudgetTests(TestCase):
    def test_august_is_one_third_of_q3(self):
        recs = [
            _irpf("IRPF Pago Fraccionado 2026 Q3", Decimal("-2988.26"), date(2026, 10, 20)),
            _irpf("IRPF Pago Fraccionado 2026 Q4", Decimal("-2988.26"), date(2027, 1, 20)),
        ]
        got = irpf_monthly_in_window(recs, date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(got, Decimal("2988.26") / 3)

    def test_year_sums_unpaid_quarters(self):
        recs = [
            _irpf("IRPF Pago Fraccionado 2026 Q3", Decimal("-2988.26"), date(2026, 10, 20)),
            _irpf("IRPF Pago Fraccionado 2026 Q4", Decimal("-2988.26"), date(2027, 1, 20)),
        ]
        got = irpf_monthly_in_window(recs, date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(got, Decimal("2988.26") * 2)


class RecPlannedTests(TestCase):
    def test_quarterly_in_august_is_a_month_share(self):
        rec = SimpleNamespace(
            amount=Decimal("-300"),
            frequency="quarter",
            start_date=date(2026, 8, 22),
            end_date=None,
        )
        got = rec_planned(rec, date(2026, 8, 1), date(2026, 8, 31))
        self.assertGreater(got, 0)
        self.assertLess(got, Decimal("300"))

