"""Import sample client/personal documents into the registry."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand

from core.models import Client, Document

NETGURU_DIR = Path(
    "/Users/oleksiyzelenyuk/Library/Mobile Documents/com~apple~CloudDocs/"
    "[00] Root/[01] Documents/[01] Oleksiy/[02] Spanish/[02] Autonomo/"
    "[04] Agreements/[02] NetGuru"
)
AUTONOMO_DIR = Path(
    "/Users/oleksiyzelenyuk/Library/Mobile Documents/com~apple~CloudDocs/"
    "[00] Root/[01] Documents/[01] Oleksiy/[02] Spanish/[02] Autonomo"
)
DOWNLOADS = Path("/Users/oleksiyzelenyuk/Downloads")


def _guess_date(name: str) -> date | None:
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", name)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(20\d{2})", name)
    if m:
        return date(int(m.group(1)), 1, 1)
    return None


def _guess_kind(name: str, personal: bool) -> str:
    lower = name.lower()
    if personal:
        if "certificado" in lower or "residencia" in lower:
            return Document.KIND_TAX_CERTIFICATE
        if re.search(r"\bm\d{3}\b", lower) or "modelo" in lower:
            return Document.KIND_TAX_DECLARATION
        return Document.KIND_OTHER
    if "order" in lower:
        return Document.KIND_ORDER
    if "offer" in lower or "oferta" in lower:
        return Document.KIND_OFFER
    if "owu" in lower or "agreement" in lower or "contract" in lower:
        return Document.KIND_AGREEMENT
    return Document.KIND_OTHER


class Command(BaseCommand):
    help = "Import Netguru agreements and personal tax PDFs into the document registry."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="")

    def handle(self, *args, **options):
        User = get_user_model()
        user = (
            User.objects.filter(username=options["username"]).first()
            if options["username"]
            else User.objects.order_by("id").first()
        )
        if not user:
            self.stderr.write("No user found.")
            return

        client = (
            Client.objects.filter(owner=user, name__icontains="NETGURU").first()
            or Client.objects.filter(owner=user).first()
        )
        if not client:
            self.stderr.write("No client found — run seed_invoicing first.")
            return

        items: list[tuple[Path, Client | None, str]] = []
        if NETGURU_DIR.is_dir():
            for path in sorted(NETGURU_DIR.glob("*.pdf")):
                items.append((path, client, _guess_kind(path.name, personal=False)))
        for path in sorted(DOWNLOADS.glob("M*-2026*.pdf")):
            items.append((path, None, Document.KIND_TAX_DECLARATION))
        cert = AUTONOMO_DIR / "CERTIFICADO DE RESIDENCIA FISCAL POSITIVO.pdf"
        if cert.is_file():
            items.append((cert, None, Document.KIND_TAX_CERTIFICATE))

        created = 0
        for path, doc_client, kind in items:
            if Document.objects.filter(
                owner=user, original_filename=path.name
            ).exists():
                self.stdout.write(f"Exists: {path.name}")
                continue
            title = path.stem
            with path.open("rb") as fh:
                doc = Document(
                    owner=user,
                    client=doc_client,
                    kind=kind,
                    title=title,
                    document_date=_guess_date(path.name),
                    original_filename=path.name,
                )
                doc.file.save(path.name, File(fh), save=True)
            created += 1
            scope = doc_client.name if doc_client else "Personal"
            self.stdout.write(f"Imported [{kind}] {scope}: {path.name}")

        self.stdout.write(self.style.SUCCESS(f"Done. {created} new document(s)."))
