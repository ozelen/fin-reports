from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase

from core.models import Account, PurchaseItem, Receipt, Transaction, Upload
from core.receipts import ensure_placeholder, link_receipt, try_match_receipt


class ReceiptDedupeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("u", password="x")
        self.account = Account.objects.create(owner=self.user, name="Revolut")
        self.upload = Upload.objects.create(
            owner=self.user,
            original_filename="revolut.csv",
            file=ContentFile(b"x", name="revolut.csv"),
        )
        self.tx = Transaction.objects.create(
            owner=self.user,
            upload=self.upload,
            account=self.account,
            operation_date=date(2026, 8, 29),
            concept="Consum",
            counterparty="Consum",
            amount=Decimal("-45.17"),
            currency="EUR",
            dedupe_hash="bank-consum",
        )

    def _receipt(self, **kwargs):
        defaults = dict(
            owner=self.user,
            merchant="consum",
            amount=Decimal("45.17"),
            currency="EUR",
            document_date=date(2026, 8, 29),
        )
        defaults.update(kwargs)
        return Receipt.objects.create(**defaults)

    def _lines(self, receipt, n, tx=None):
        PurchaseItem.objects.bulk_create(
            [
                PurchaseItem(
                    receipt=receipt, transaction=tx, name=f"item {i}", amount=Decimal("1")
                )
                for i in range(n)
            ]
        )

    def test_second_receipt_on_same_bank_row_replaces_the_first(self):
        first = self._receipt()
        first.transaction = self.tx
        first.save(update_fields=["transaction"])
        self._lines(first, 14, tx=self.tx)

        second = self._receipt()
        self._lines(second, 14)
        link_receipt(second, self.tx)

        self.assertFalse(Receipt.objects.filter(pk=first.pk).exists())
        self.assertEqual(Receipt.objects.filter(transaction=self.tx).count(), 1)
        self.assertEqual(PurchaseItem.objects.filter(transaction=self.tx).count(), 14)
        second.refresh_from_db()
        self.assertEqual(second.transaction_id, self.tx.id)

    def test_try_match_replaces_existing_receipt(self):
        first = self._receipt()
        link_receipt(first, self.tx)
        self._lines(first, 14, tx=self.tx)

        second = self._receipt()
        try_match_receipt(second)
        self._lines(second, 14, tx=second.transaction)

        self.assertEqual(Receipt.objects.filter(transaction=self.tx).count(), 1)
        self.assertEqual(PurchaseItem.objects.filter(transaction=self.tx).count(), 14)

    def test_placeholder_reuses_same_merchant_amount(self):
        first = self._receipt()
        ensure_placeholder(first)
        self._lines(first, 5, tx=first.transaction)

        second = self._receipt()
        ensure_placeholder(second)
        self._lines(second, 5, tx=second.transaction)

        self.assertEqual(second.transaction_id, first.transaction_id)
        self.assertFalse(Receipt.objects.filter(pk=first.pk).exists())
        self.assertEqual(PurchaseItem.objects.filter(transaction=second.transaction).count(), 5)
