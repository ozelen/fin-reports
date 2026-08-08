from django.core.management.base import BaseCommand

from core.models import Transaction
from core.parsing import extract_counterparty


class Command(BaseCommand):
    help = "Populate Transaction.counterparty for existing rows from their concept."

    def add_arguments(self, parser):
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Also recompute rows that already have a counterparty.",
        )

    def handle(self, *args, **options):
        qs = Transaction.objects.all()
        if not options["overwrite"]:
            qs = qs.filter(counterparty="")

        updated = []
        for tx in qs.iterator():
            value = extract_counterparty(tx.concept)
            if value != tx.counterparty:
                tx.counterparty = value
                updated.append(tx)

        Transaction.objects.bulk_update(updated, ["counterparty"], batch_size=500)
        self.stdout.write(
            self.style.SUCCESS(f"Updated counterparty on {len(updated)} transaction(s).")
        )
