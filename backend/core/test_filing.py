from datetime import date
from unittest import TestCase

from core.filing import classify_upload, date_from_filename, pdf_creation_date
from core.models import Document


class ClassifyUploadTests(TestCase):
    def test_modelos_are_tax_declarations(self):
        self.assertEqual(
            classify_upload("M130-2T-2026-ZELENYUK OLEKSIY.pdf"),
            Document.KIND_TAX_DECLARATION,
        )
        self.assertEqual(
            classify_upload("M303-2T-2026-ZELENYUK OLEKSIY.pdf"),
            Document.KIND_TAX_DECLARATION,
        )
        self.assertEqual(
            classify_upload("M349-2T-2026-ZELENYUK OLEKSIY.pdf"),
            Document.KIND_TAX_DECLARATION,
        )

    def test_factura_is_invoice(self):
        self.assertEqual(classify_upload("Factura F-26-000137.pdf"), "invoice")

    def test_photo_is_receipt(self):
        self.assertEqual(classify_upload("photo.jpg"), "receipt")

    def test_trimestre_date(self):
        self.assertEqual(date_from_filename("M130-2T-2026.pdf"), date(2026, 6, 30))

    def test_pdf_creation_date(self):
        data = b"%PDF-1.4\n/CreationDate (D:20260716125223+00'00')\n"
        self.assertEqual(pdf_creation_date(data), date(2026, 7, 16))
