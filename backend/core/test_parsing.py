import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase

from core.parsing import _detect_currency, dedupe_hash, parse


class DedupeHashTests(SimpleTestCase):
    def test_concept_case_does_not_change_hash(self):
        day = date(2026, 7, 8)
        amount = Decimal("5280.00")
        balance = Decimal("5678.24")
        self.assertEqual(
            dedupe_hash(day, amount, "Transferencia De Netguru S.a., Concepto 26070201.", balance),
            dedupe_hash(day, amount, "TRANSFERENCIA DE NETGURU S.A., CONCEPTO 26070201.", balance),
        )

    def test_amount_scale_does_not_change_hash(self):
        day = date(2026, 7, 8)
        concept = "Transferencia De Netguru S.a., Concepto 26070201."
        self.assertEqual(
            dedupe_hash(day, Decimal("5280.0"), concept, Decimal("5678.24")),
            dedupe_hash(day, Decimal("5280.00"), concept, Decimal("5678.24")),
        )


class MonobankCurrencyTests(SimpleTestCase):
    def test_header_uah_wins_over_first_fx_row(self):
        header = [
            "Date and time",
            "Description",
            "MCC",
            "Card currency amount, (UAH)",
            "Operation amount",
            "Operation currency",
            "Balance",
        ]
        matrix = [
            header,
            ["06.09.2026 17:50:56", "ExpressVPN", "7372", "-580.17", "-12.95", "USD", "160963.19"],
        ]
        self.assertEqual(_detect_currency(matrix, header), "UAH")

    def test_parse_keeps_card_amount_in_uah(self):
        csv = (
            "Date and time,Description,MCC,"
            '"Card currency amount, (UAH)",Operation amount,Operation currency,Balance\n'
            "06.09.2026 17:50:56,ExpressVPN,7372,-580.17,-12.95,USD,160963.19\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.csv"
            path.write_text(csv, encoding="utf-8")
            result = parse(str(path), "report.csv")
        self.assertEqual(result["meta"]["currency"], "UAH")
        row = result["rows"][0]
        self.assertEqual(row["currency"], "UAH")
        self.assertEqual(row["amount"], Decimal("-580.17"))
        self.assertEqual(row["metadata"]["operation_currency"], "USD")
        self.assertEqual(row["metadata"]["operation_amount"], "-12.95")
        self.assertFalse(row["_currency_explicit"])
