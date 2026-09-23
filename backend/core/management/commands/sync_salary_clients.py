"""Create historical/current clients, upload agreements, match salary inflows."""
from datetime import date
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db.models import Count

from core.clients import backfill
from core.models import Client, Document

PINUP_NAMES = (
    "pinup.pdf",
    "Software_development_Oleksiy_Zelenyuk_signed_both.pdf",
    "Software development_Oleksiy Zelenyuk_signed_both.pdf",
)
BLACKTHORN_NAMES = (
    "blackthorn.pdf",
    "SA_DEV0226_BlackthornAI_Oleksiy_Zelenyuk.pdf",
    "SA DEV0226 BlackthornAI_Oleksiy Zelenyuk.pdf",
)

PINUP_DOCS = [
    Path("/tmp/pinup.pdf"),
    Path("/tmp/agreements") / PINUP_NAMES[1],
    Path(
        "/Users/oleksiyzelenyuk/.cursor/projects/Users-oleksiyzelenyuk-Projects-income-share/"
        "attachments/d2f081fb-4e2c-49a9-a0b6-cf83ee676160/"
        "Software_development_Oleksiy_Zelenyuk_signed_both.pdf"
    ),
    Path(
        "/Users/oleksiyzelenyuk/Library/Mobile Documents/com~apple~CloudDocs/"
        "[00] Root/[01] Documents/[01] Oleksiy/[02] Spanish/[02] Autonomo/"
        "[04] Agreements/[01] Pin-Up/Software development_Oleksiy Zelenyuk_signed_both.pdf"
    ),
]
BLACKTHORN_DOCS = [
    Path("/tmp/blackthorn.pdf"),
    Path("/tmp/agreements") / BLACKTHORN_NAMES[1],
    Path(
        "/Users/oleksiyzelenyuk/.cursor/projects/Users-oleksiyzelenyuk-Projects-income-share/"
        "attachments/d2f081fb-4e2c-49a9-a0b6-cf83ee676160/"
        "SA_DEV0226_BlackthornAI_Oleksiy_Zelenyuk.pdf"
    ),
    Path(
        "/Users/oleksiyzelenyuk/Library/Mobile Documents/com~apple~CloudDocs/"
        "[00] Root/[01] Documents/[01] Oleksiy/[02] Spanish/[02] Autonomo/"
        "[04] Agreements/Blackthorn/SA DEV0226 BlackthornAI_Oleksiy Zelenyuk.pdf"
    ),
]

AUTODESK_DIR = Path(
    "/Users/oleksiyzelenyuk/Library/Mobile Documents/com~apple~CloudDocs/"
    "[00] Root/[03] Job/[06] Autodesk"
)
AUTODESK_REMOTE = Path("/tmp/agreements")

CLIENTS = [
    {
        "name": "NETGURU SPÓŁKA AKCYJNA",
        "defaults": {
            "short_name": "Netguru",
            "tax_id": "7781454968",
            "address": "ul. Małe Garbary 9 61-756 Poznań",
            "vat_mode": Client.VAT_REVERSE_CHARGE,
            "default_description": "Travel Zone - post MVP",
            "billing_unit": Client.UNIT_HOUR,
            "default_unit_price": 30,
            "currency": "EUR",
            "match_text": "NETGURU",
            "active_from": date(2026, 4, 1),
            "notes": "Foreign contractor — reverse charge / NP. Submit before 5th working day.",
        },
    },
    {
        "name": "JKO Connect Enterprises Limited",
        "defaults": {
            "short_name": "JKO Connect",
            "vat_mode": Client.VAT_REVERSE_CHARGE,
            "billing_unit": Client.UNIT_HOUR,
            "default_unit_price": 0,
            "currency": "EUR",
            "match_text": "Jko Connect",
            "active_from": date(2025, 1, 1),
            "active_to": date(2025, 7, 31),
            "notes": (
                "Historical. No agreement on file. Payments were a declining monthly "
                "retainer. VAT assumed reverse charge (foreign B2B)."
            ),
        },
    },
    {
        "name": "Guruflow Team Ltd",
        "defaults": {
            "short_name": "Pin-Up",
            "tax_id": "HE 405280",
            "address": "Vasili Michailidi, 9, Limassol, Cyprus, 3026",
            "vat_mode": Client.VAT_REVERSE_CHARGE,
            "default_description": "Software Infrastructure engineering",
            "billing_unit": Client.UNIT_HOUR,
            "default_unit_price": 50,
            "currency": "EUR",
            "match_text": "Guruflow",
            "active_from": date(2024, 10, 1),
            "active_to": date(2025, 5, 31),
            "notes": (
                "Pin-Up project. Legal entity Guruflow Team Ltd (Cyprus). "
                "Agreement 1 Oct 2024, 50 EUR/hour. Reverse charge (EU B2B)."
            ),
        },
        "docs": [
            {
                "paths": PINUP_DOCS,
                "aliases": PINUP_NAMES,
                "title": "Agreement for rendering of services — Guruflow / Pin-Up",
                "document_date": date(2024, 10, 1),
                "starts_on": date(2024, 10, 1),
                "ends_on": date(2025, 5, 31),
            }
        ],
    },
    {
        "name": "Softermii Inc",
        "defaults": {
            "short_name": "Softermii",
            "vat_mode": Client.VAT_REVERSE_CHARGE,
            "billing_unit": Client.UNIT_HOUR,
            "default_unit_price": 0,
            "currency": "EUR",
            "match_text": "Softermii",
            "active_from": date(2025, 11, 1),
            "active_to": date(2026, 3, 31),
            "notes": (
                "Historical. Payments arrived from Softermii Inc and Softermii Ou. "
                "No agreement on file. VAT assumed reverse charge (foreign B2B)."
            ),
        },
    },
    {
        "name": "Blackthorn AI LTD",
        "defaults": {
            "short_name": "Blackthorn",
            "tax_id": "13335565",
            "address": "Kemp House 128 City Road, London, United Kingdom, EC1V 2NX",
            "vat_mode": Client.VAT_REVERSE_CHARGE,
            "default_description": "Software development services",
            "billing_unit": Client.UNIT_HOUR,
            "default_unit_price": 30,
            "currency": "USD",
            "match_text": "Blackthorn",
            "active_from": date(2026, 1, 26),
            "active_to": date(2026, 3, 31),
            "notes": (
                "SA DEV0226, effective 26 Jan 2026. 30 USD/hour, monthly invoice. "
                "UK B2B — reverse charge / not subject to Spanish VAT. "
                "Active dates follow bank payments (ended before Netguru)."
            ),
        },
        "docs": [
            {
                "paths": BLACKTHORN_DOCS,
                "aliases": BLACKTHORN_NAMES,
                "title": "Services Agreement DEV0226 — Blackthorn AI",
                "document_date": date(2026, 1, 26),
                "starts_on": date(2026, 1, 26),
                "ends_on": date(2026, 3, 31),
            }
        ],
    },
    {
        "name": "Quarrymare Limited",
        "defaults": {
            "short_name": "Autodesk",
            "tax_id": "IE3388274LH",
            "address": (
                "Block D, Tyrrelstown Plaza, Tyrrelstown, Dublin 15, "
                "D15 K4PY, Ireland"
            ),
            "vat_mode": Client.VAT_REVERSE_CHARGE,
            "default_description": "Senior Solutions Architect",
            "billing_unit": Client.UNIT_DAY,
            "default_unit_price": 410,
            "currency": "EUR",
            "match_text": "Quarrymare",
            "active_from": date(2026, 9, 21),
            "active_to": date(2027, 3, 20),
            "notes": (
                "Autodesk (Barcelona) via CPL Solutions Limited. "
                "Bill-to is TIFO umbrella Quarrymare Limited (Fenero, CRO 568284). "
                "CPL self-bills Quarrymare. €410/day, 37.5h week. "
                "Reverse charge (IE B2B)."
            ),
        },
        "docs": [
            {
                "paths": [
                    AUTODESK_REMOTE / "autodesk-contract.pdf",
                    AUTODESK_DIR / "Oleksiy_Zelenyuk__Autodesk_September_2026_SIGNED (2).pdf",
                ],
                "aliases": ("autodesk-contract.pdf",),
                "title": "Contract for services — CPL / Quarrymare (Autodesk)",
                "document_date": date(2026, 9, 15),
                "starts_on": date(2026, 9, 21),
                "ends_on": date(2027, 3, 20),
            },
            {
                "paths": [
                    AUTODESK_REMOTE / "autodesk-nda.pdf",
                    AUTODESK_DIR
                    / "Autodesk Contingent Worker Onboarding Documents_NDA_SIGNED.pdf",
                ],
                "aliases": ("autodesk-nda.pdf",),
                "kind": Document.KIND_OTHER,
                "title": "Autodesk contingent worker NDA / onboarding",
                "document_date": date(2026, 9, 10),
                "starts_on": date(2026, 9, 10),
                "ends_on": None,
            },
            {
                "paths": [
                    AUTODESK_REMOTE / "autodesk-insurance.pdf",
                    AUTODESK_DIR / "Fenero Umbrella Insurance Certificate 26-27 (1).pdf",
                ],
                "aliases": ("autodesk-insurance.pdf",),
                "kind": Document.KIND_OTHER,
                "title": "Fenero umbrella insurance certificate 2026–27",
                "document_date": date(2026, 6, 19),
                "starts_on": date(2026, 6, 27),
                "ends_on": date(2027, 6, 26),
            },
            {
                "paths": [
                    AUTODESK_REMOTE / "autodesk-policy.pdf",
                    AUTODESK_DIR / "Policy Schedule Document - Shareable (1) (1).pdf",
                ],
                "aliases": ("autodesk-policy.pdf",),
                "kind": Document.KIND_OTHER,
                "title": "Fenero umbrella policy schedule 2026–27",
                "document_date": date(2026, 6, 19),
                "starts_on": date(2026, 6, 27),
                "ends_on": date(2027, 6, 26),
            },
        ],
    },
]


def _first_existing(paths):
    for path in paths:
        if path.is_file():
            return path
    return None


def _resolve_doc(doc, docs_dir):
    candidates = []
    if docs_dir:
        for name in doc.get("aliases") or ():
            candidates.append(docs_dir / name)
        for path in doc["paths"]:
            candidates.append(docs_dir / path.name)
    candidates.extend(doc["paths"])
    return _first_existing(candidates)


class Command(BaseCommand):
    help = "Upsert salary clients, upload known agreements, match bank inflows."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="")
        parser.add_argument("--name", default="", help="Only upsert this client legal name.")
        parser.add_argument(
            "--docs-dir",
            default="",
            help="Folder of agreement PDFs (pinup.pdf / blackthorn.pdf / autodesk-*.pdf).",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        if options["username"]:
            user = User.objects.filter(username=options["username"]).first()
        else:
            user = (
                User.objects.annotate(n=Count("transactions"))
                .order_by("-n", "id")
                .first()
            )
        if not user:
            self.stderr.write("No user found.")
            return

        docs_dir = Path(options["docs_dir"]) if options["docs_dir"] else None

        for spec in CLIENTS:
            if options["name"] and spec["name"] != options["name"]:
                continue
            client, created = Client.objects.update_or_create(
                owner=user, name=spec["name"], defaults=spec["defaults"]
            )
            verb = "Created" if created else "Updated"
            self.stdout.write(f"{verb}: {client.display_name()} ({client.name})")
            for doc in spec.get("docs") or []:
                path = _resolve_doc(doc, docs_dir)
                if not path:
                    self.stderr.write(f"  Missing file for {doc['title']}")
                    continue
                existing = Document.objects.filter(
                    owner=user, client=client, title=doc["title"]
                ).first()
                starts = doc.get("starts_on") or doc["document_date"]
                ends = doc["ends_on"] if "ends_on" in doc else spec["defaults"].get("active_to")
                if existing:
                    fields = []
                    if not existing.starts_on and starts:
                        existing.starts_on = starts
                        fields.append("starts_on")
                    if not existing.ends_on and ends:
                        existing.ends_on = ends
                        fields.append("ends_on")
                    if fields:
                        existing.save(update_fields=fields)
                    self.stdout.write(f"  Doc exists: {doc['title']}")
                    continue
                with path.open("rb") as fh:
                    row = Document(
                        owner=user,
                        client=client,
                        kind=doc.get("kind", Document.KIND_AGREEMENT),
                        title=doc["title"],
                        document_date=doc["document_date"],
                        starts_on=starts,
                        ends_on=ends,
                        original_filename=path.name,
                    )
                    row.file.save(path.name, File(fh), save=True)
                self.stdout.write(f"  Uploaded: {path.name}")

        matched = backfill(user)
        self.stdout.write(f"Matched {matched} salary transaction(s) to clients.")
