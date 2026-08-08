"""Seed issuer profile, Netguru client, Revolut invoice account; optionally import XLSX."""
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core import invoicing
from core.models import Account, Client, Invoice, IssuerProfile


class Command(BaseCommand):
    help = "Seed invoicing defaults (issuer, Netguru, Revolut) and optionally import XLSX files."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="")
        parser.add_argument(
            "--import-dir",
            default="",
            help="Directory of Netguru .xlsx invoices to import as issued",
        )

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

        profile, _ = IssuerProfile.objects.update_or_create(
            owner=user,
            defaults={
                "legal_name": "Oleksiy Zelenyuk",
                "vat_number": "ESZ0497876T",
                "address": "Carrer Picaio 9 p5, Puçol, Valencia 46530, España",
                "city": "Valencia",
                "country": "Spain",
                "phone": "34 605-817-513",
                "email": "o@zelen.uk",
                "legal_form": "Private Entrepreneur | Autónomo",
            },
        )
        self.stdout.write(f"Issuer: {profile.legal_name}")

        account, _ = Account.objects.update_or_create(
            owner=user,
            name="Revolut",
            defaults={
                "bank": "Revolut Bank UAB",
                "iban": "ES1915830001119099058403",
                "bic": "REVOESM2",
                "correspondent_bic": "CHASDEFX",
                "bank_address": (
                    "Revolut Bank UAB, Calle Príncipe de Vergara 132, 4 planta, "
                    "28002, Madrid, Spain"
                ),
                "currency": "EUR",
                "is_invoice_default": True,
            },
        )
        Account.objects.filter(owner=user).exclude(id=account.id).update(
            is_invoice_default=False
        )
        self.stdout.write(f"Invoice account: {account.name} ({account.iban})")

        client, _ = Client.objects.update_or_create(
            owner=user,
            name="NETGURU SPÓŁKA AKCYJNA",
            defaults={
                "tax_id": "7781454968",
                "address": "ul. Małe Garbary 9 61-756 Poznań",
                "vat_mode": Client.VAT_REVERSE_CHARGE,
                "default_vat_rate": 0,
                "default_description": "Travel Zone - post MVP",
                "default_unit_price": 30,
                "currency": "EUR",
                "notes": "Foreign contractor — reverse charge / NP. Submit before 5th working day.",
            },
        )
        self.stdout.write(f"Client: {client.name}")

        import_dir = options["import_dir"]
        if not import_dir:
            return

        folder = Path(import_dir)
        if not folder.is_dir():
            self.stderr.write(f"Not a directory: {folder}")
            return

        for path in sorted(folder.glob("*.xlsx")):
            if "AutoRecovered" in path.name:
                continue
            parsed = invoicing.parse_invoice_xlsx(path)
            number = parsed["number"]
            if not number or not parsed["issue_date"] or not parsed["sale_date"]:
                self.stderr.write(f"Skip (incomplete): {path.name}")
                continue
            if Invoice.objects.filter(owner=user, number=number).exists():
                self.stdout.write(f"Exists: #{number}")
                continue

            invoice = Invoice(
                owner=user,
                status=Invoice.STATUS_DRAFT,
                number=number,
                client=client,
                account=account,
                service_year=parsed["sale_date"].year,
                service_month=parsed["sale_date"].month,
                issue_date=parsed["issue_date"],
                sale_date=parsed["sale_date"],
                due_date=parsed["due_date"],
                description=parsed["description"] or client.default_description,
                quantity=parsed["quantity"],
                unit_price=parsed["unit_price"] or client.default_unit_price,
                currency=client.currency,
            )
            invoicing.apply_snapshots(invoice)
            for key in (
                "iban",
                "bic",
                "correspondent_bic",
                "bank_address",
                "issuer_name",
                "issuer_phone",
                "issuer_email",
                "issuer_vat_number",
                "issuer_address",
                "issuer_legal_form",
                "client_name",
                "client_address",
            ):
                if parsed.get(key):
                    setattr(invoice, key, parsed[key])
            invoice.recalculate_amounts()
            invoicing.attach_generated_files(invoice)
            invoice.status = Invoice.STATUS_ISSUED
            from django.utils import timezone

            invoice.issued_at = timezone.now()
            invoice.save()
            self.stdout.write(
                f"Imported #{invoice.number} {invoice.quantity}h → {invoice.total_amount} {invoice.currency}"
            )
