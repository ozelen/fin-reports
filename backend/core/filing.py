"""Classify Telegram/web uploads: tax PDFs vs invoices vs receipts."""
from __future__ import annotations

import calendar
import datetime as dt
import re
from pathlib import Path

from django.core.files.base import ContentFile

from .models import Document

_MODELO = re.compile(r"\bM(\d{3})\b", re.I)
_FACTURA = re.compile(r"factura|\bf-\d{2,}", re.I)
_TRIMESTRE = re.compile(r"(\d)T[-_]?(\d{4})", re.I)
_ISO = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")
_PDF_CREATED = re.compile(rb"/CreationDate\s*\(D:(\d{8})")


def classify_upload(filename: str) -> str:
    """receipt | invoice | tax_declaration | tax_certificate | other_document"""
    name = filename or ""
    low = name.lower()
    if _FACTURA.search(name):
        return "invoice"
    if "certificado" in low or "residencia fiscal" in low:
        return Document.KIND_TAX_CERTIFICATE
    if _MODELO.search(name) or "modelo" in low or "justificante" in low:
        return Document.KIND_TAX_DECLARATION
    if low.endswith(".pdf"):
        return "other_document"
    return "receipt"


def date_from_filename(name: str) -> dt.date | None:
    m = _TRIMESTRE.search(name or "")
    if m:
        quarter, year = int(m.group(1)), int(m.group(2))
        month = min(max(quarter, 1), 4) * 3
        last = calendar.monthrange(year, month)[1]
        return dt.date(year, month, last)
    m = _ISO.search(name or "")
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def pdf_creation_date(data: bytes) -> dt.date | None:
    m = _PDF_CREATED.search(data or b"")
    if not m:
        return None
    raw = m.group(1).decode()
    return dt.date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))


def save_personal_document(user, data: bytes, filename: str, kind: str) -> Document:
    title = Path(filename).stem.replace("_", " ")
    doc = Document(
        owner=user,
        client=None,
        kind=kind if kind in dict(Document.KIND_CHOICES) else Document.KIND_OTHER,
        title=title,
        original_filename=filename,
        document_date=date_from_filename(filename),
    )
    doc.save()
    if data:
        doc.file.save(Path(filename).name or "document.pdf", ContentFile(data), save=True)
    return doc
