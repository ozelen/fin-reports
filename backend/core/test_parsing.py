from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from core.parsing import dedupe_hash


class DedupeHashTests(SimpleTestCase):
    def test_concept_case_does_not_change_hash(self):
        day = date(2026, 7, 8)
        amount = Decimal("5280.00")
        balance = Decimal("5678.24")
        self.assertEqual(
            dedupe_hash(day, amount, "Transferencia De Netguru S.a., Concepto 26070201.", balance),
            dedupe_hash(day, amount, "TRANSFERENCIA DE NETGURU S.A., CONCEPTO 26070201.", balance),
        )
