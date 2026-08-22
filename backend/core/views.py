import datetime as dt
import tempfile
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from django.core import serializers as dj_serializers
from django.core.management.color import no_style
from django.db import connection, transaction as db_transaction
from django.db.models import CharField, Count, IntegerField, OuterRef, Q, Subquery, Sum
from django.db.models.functions import (
    Coalesce,
    TruncDay,
    TruncMonth,
    TruncQuarter,
    TruncWeek,
    TruncYear,
)
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from . import ai, parsing
from .criteria import apply_criteria
from .export import build_workbook
from .filters import TransactionFilter
from .folders import descendants, folder_transaction_ids, own_transaction_ids, subtree
from . import invoicing
from .fx import Converter, _unique, exclude_ignored, series_eur, summarize_eur
from .receipts import (
    candidate_transactions,
    ingest_statement,
    link_receipt,
    set_item_tags,
    try_match_receipt,
    window_days,
)
from .models import (
    Account,
    Budget,
    Client,
    Document,
    Folder,
    Invoice,
    IssuerProfile,
    PurchaseItem,
    Receipt,
    Recurrence,
    Rule,
    Tag,
    TaxProfile,
    Transaction,
    TransactionTag,
    Upload,
)
from .rules import apply_rules
from .serializers import (
    AccountSerializer,
    AiApplySerializer,
    AiClassifySerializer,
    BudgetSerializer,
    BulkTagSerializer,
    ClientSerializer,
    DocumentSerializer,
    FolderSerializer,
    FolderTransactionsSerializer,
    FromTransactionSerializer,
    InvoiceSerializer,
    IssuerProfileSerializer,
    PurchaseItemSerializer,
    ReceiptSerializer,
    RecurrenceAttachSerializer,
    RecurrenceSerializer,
    RuleSerializer,
    TagSerializer,
    TaxProfileSerializer,
    TransactionSerializer,
    TransferSerializer,
    UploadSerializer,
)
from .accounts import book_transfer


class UploadViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = UploadSerializer
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        return Upload.objects.filter(owner=self.request.user)

    def _resolve_account(self, request):
        """Pick the bank account for this upload: requested, else default, else first."""
        banks = Account.objects.filter(owner=request.user, kind=Account.KIND_BANK)
        account_id = request.data.get("account")
        if account_id:
            account = banks.filter(id=account_id).first()
            if account is not None:
                return account
            if Account.objects.filter(owner=request.user, id=account_id).exists():
                raise ValidationError({"account": "Statements go into a bank account."})
        return banks.filter(is_default=True).first() or banks.order_by("id").first()

    def create(self, request, *args, **kwargs):
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response(
                {"detail": "No file provided (expected form field 'file')."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        account = self._resolve_account(request)

        upload = Upload.objects.create(
            owner=request.user,
            account=account,
            original_filename=file_obj.name,
            file=file_obj,
        )

        try:
            result = parsing.parse(upload.file.path, upload.original_filename)
        except (parsing.UnsupportedFormat, parsing.ParseError) as exc:
            upload.delete()
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001 - surface parser issues to the client
            upload.delete()
            return Response(
                {"detail": f"Failed to parse file: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        extra = ingest_statement(request.user, upload, account, result)

        serializer = self.get_serializer(upload)
        data = serializer.data
        data["skipped_duplicates"] = extra["skipped"]
        data["rule_assignments"] = extra["rule_assignments"]
        data["receipts_attached"] = extra["receipts_attached"]
        data["receipts_enriched"] = extra["receipts_enriched"]
        return Response(data, status=status.HTTP_201_CREATED)


class TransactionViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = TransactionSerializer
    filterset_class = TransactionFilter
    search_fields = ["concept", "counterparty"]
    ordering_fields = [
        "operation_date",
        "value_date",
        "amount",
        "balance",
        "concept",
        "counterparty",
    ]
    ordering = ["-operation_date", "-id"]

    def get_queryset(self):
        receipt_id = Subquery(
            Receipt.objects.filter(transaction_id=OuterRef("pk"))
            .order_by("id")
            .values("id")[:1],
            output_field=IntegerField(),
        )
        receipt_kind = Subquery(
            Receipt.objects.filter(transaction_id=OuterRef("pk"))
            .order_by("id")
            .values("kind")[:1],
            output_field=CharField(),
        )
        item_count = Coalesce(
            Subquery(
                PurchaseItem.objects.filter(transaction_id=OuterRef("pk"))
                .order_by()
                .values("transaction_id")
                .annotate(c=Count("id"))
                .values("c")[:1],
                output_field=IntegerField(),
            ),
            0,
        )
        return (
            Transaction.objects.filter(owner=self.request.user)
            .select_related("account", "recurrence")
            .prefetch_related("tag_links__tag")
            .annotate(
                receipt_id=receipt_id,
                receipt_kind=receipt_kind,
                item_count=item_count,
            )
        )

    @action(detail=False, methods=["get"])
    def summary(self, request):
        qs = _unique(self.filter_queryset(self.get_queryset()))
        return Response(summarize_eur(qs))

    @action(detail=False, methods=["post"])
    def tag(self, request):
        serializer = BulkTagSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        owned_tx = list(
            Transaction.objects.filter(
                owner=request.user, id__in=data["transaction_ids"]
            )
        )
        add_tags = Tag.objects.filter(owner=request.user, id__in=data["add"])
        created = 0
        for tx in owned_tx:
            for tag in add_tags:
                _, was_created = TransactionTag.objects.get_or_create(
                    transaction=tx,
                    tag=tag,
                    defaults={"source": TransactionTag.SOURCE_MANUAL},
                )
                if was_created:
                    created += 1
        if data["remove"]:
            TransactionTag.objects.filter(
                transaction__in=owned_tx, tag_id__in=data["remove"]
            ).delete()

        return Response({"updated": len(owned_tx), "created": created})

    @action(detail=False, methods=["get"])
    def by_tag(self, request):
        """Aggregate the filtered transactions per tag for dashboard charts."""
        qs = exclude_ignored(_unique(self.filter_queryset(self.get_queryset())))
        totals = summarize_eur(qs)
        currency_codes = [c["currency"] for c in totals["currencies"]]
        needs_fx = any(c.upper() != "EUR" for c in currency_codes)
        conv = None
        if needs_fx:
            pairs = list(qs.values_list("operation_date", "currency"))
            conv = Converter([d for d, _ in pairs], [c for _, c in pairs])

        def as_eur(amount, currency, day, sign=1):
            raw = amount or 0
            if conv is None:
                return float(raw) * sign
            converted = conv.to_eur(raw, currency, day)
            return float(converted) * sign if converted is not None else 0.0

        split_ids = set(
            PurchaseItem.objects.filter(
                transaction__in=qs, tags__isnull=False
            ).values_list("transaction_id", flat=True)
        )
        by_id = {}
        counted = defaultdict(set)

        def add(tag_id, name, color, amount, currency, day, tx_id):
            eur = as_eur(amount, currency, day)
            entry = by_id.setdefault(
                tag_id,
                {
                    "id": tag_id,
                    "name": name,
                    "color": color,
                    "count": 0,
                    "income": 0.0,
                    "expense": 0.0,
                    "net": 0.0,
                },
            )
            if tx_id not in counted[tag_id]:
                counted[tag_id].add(tx_id)
                entry["count"] += 1
            if eur >= 0:
                entry["income"] += eur
            else:
                entry["expense"] += eur
            entry["net"] = entry["income"] + entry["expense"]

        # One transaction, one amount: split equally across its tags.
        links = list(
            TransactionTag.objects.filter(transaction__in=qs)
            .exclude(transaction_id__in=split_ids)
            .values(
                "tag_id",
                "tag__name",
                "tag__color",
                "transaction_id",
                "transaction__amount",
                "transaction__operation_date",
                "transaction__currency",
            )
        )
        n_tags = Counter(r["transaction_id"] for r in links)
        for r in links:
            n = n_tags[r["transaction_id"]] or 1
            share = (r["transaction__amount"] or 0) / n
            add(
                r["tag_id"],
                r["tag__name"],
                r["tag__color"],
                share,
                r["transaction__currency"],
                r["transaction__operation_date"],
                r["transaction_id"],
            )

        # Mixed-cart receipts: give the whole check once, split by item-tag weight.
        weights = defaultdict(lambda: defaultdict(lambda: Decimal("0")))
        tag_meta = {}
        tx_meta = {}
        for item in (
            PurchaseItem.objects.filter(
                transaction_id__in=split_ids, tags__isnull=False
            )
            .prefetch_related("tags")
            .select_related("transaction")
        ):
            tx = item.transaction
            if not tx:
                continue
            tx_meta[tx.id] = (tx.operation_date, tx.currency, tx.amount or 0)
            for tag in item.tags.all():
                weights[tx.id][tag.id] += item.amount or 0
                tag_meta[tag.id] = (tag.name, tag.color)
        for tx_id, tag_w in weights.items():
            day, ccy, tx_amt = tx_meta[tx_id]
            total_w = sum(tag_w.values()) or Decimal("1")
            for tag_id, w in tag_w.items():
                name, color = tag_meta[tag_id]
                add(tag_id, name, color, tx_amt * (w / total_w), ccy, day, tx_id)

        tags = sorted(by_id.values(), key=lambda t: abs(t["net"]), reverse=True)

        u = summarize_eur(qs.filter(tag_links__isnull=True))
        untagged = {
            "count": u["count"] or 0,
            "income": u["income"] or 0,
            "expense": u["expense"] or 0,
            "net": (u["income"] or 0) + (u["expense"] or 0),
        }

        return Response(
            {
                "tags": tags,
                "untagged": untagged,
                "totals": {
                    "count": totals["count"],
                    "income": totals["income"],
                    "expense": totals["expense"],
                    "net": totals["net"],
                    "currency": totals["currency"],
                },
                "mixed": totals["mixed"],
                "converted": totals["converted"],
                "currencies": currency_codes,
            }
        )

    @action(detail=False, methods=["get"])
    def over_time(self, request):
        """Income/expense/net per time bucket for the dashboard line chart.

        ``granularity`` may be day/week/month/quarter/year.
        Non-EUR amounts are converted at the NBU rate on operation_date.
        """
        qs = exclude_ignored(_unique(self.filter_queryset(self.get_queryset())))
        granularity = (request.query_params.get("granularity") or "month").lower()
        fx_series = series_eur(qs, granularity)
        if fx_series is not None:
            return Response(
                {
                    "granularity": granularity,
                    "series": fx_series["series"],
                    "mixed": fx_series["mixed"],
                    "converted": fx_series["converted"],
                    "currencies": fx_series["currencies"],
                }
            )

        currency_codes = sorted(
            {c for c in qs.values_list("currency", flat=True).distinct() if c}
        )
        trunc = {
            "day": TruncDay,
            "week": TruncWeek,
            "month": TruncMonth,
            "quarter": TruncQuarter,
            "year": TruncYear,
        }.get(granularity, TruncMonth)

        rows = (
            qs.annotate(period=trunc("operation_date"))
            .values("period")
            .annotate(
                income=Sum("amount", filter=Q(amount__gte=0)),
                expense=Sum("amount", filter=Q(amount__lt=0)),
                count=Count("id"),
            )
            .order_by("period")
        )

        def money(value):
            return float(value or 0)

        series = [
            {
                "period": r["period"].isoformat() if r["period"] else None,
                "income": money(r["income"]),
                "expense": money(r["expense"]),
                "net": money(r["income"]) + money(r["expense"]),
                "count": r["count"],
            }
            for r in rows
            if r["period"] is not None
        ]
        return Response(
            {
                "granularity": granularity,
                "series": series,
                "mixed": False,
                "converted": False,
                "currencies": currency_codes,
            }
        )


class AccountViewSet(viewsets.ModelViewSet):
    serializer_class = AccountSerializer

    def get_queryset(self):
        qs = Account.objects.filter(owner=self.request.user)
        group = self.request.query_params.get("group")
        if group:
            qs = qs.filter(group=group)
        kind = self.request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        return qs

    def perform_create(self, serializer):
        account = serializer.save(owner=self.request.user)
        self._sync_defaults(account)

    def perform_update(self, serializer):
        account = serializer.save()
        self._sync_defaults(account)

    def _sync_defaults(self, account):
        """Keep at most one upload-default and one invoice-default per owner."""
        if account.kind != Account.KIND_BANK:
            if account.is_default or account.is_invoice_default:
                Account.objects.filter(pk=account.pk).update(
                    is_default=False, is_invoice_default=False
                )
            return
        if account.is_default:
            Account.objects.filter(owner=account.owner).exclude(
                id=account.id
            ).update(is_default=False)
        if account.is_invoice_default:
            Account.objects.filter(owner=account.owner).exclude(
                id=account.id
            ).update(is_invoice_default=False)

    @action(detail=False, methods=["post"])
    def transfer(self, request):
        serializer = TransferSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        src, dst = book_transfer(
            request.user,
            data["from_account"],
            data["to_account"],
            data["amount"],
            data["operation_date"],
            data.get("concept") or "",
        )
        return Response(
            {
                "from": AccountSerializer(src).data,
                "to": AccountSerializer(dst).data,
            },
            status=status.HTTP_201_CREATED,
        )


class IssuerProfileView(APIView):
    """GET/PUT the current user's issuer profile (create on first save)."""

    def get(self, request):
        profile = IssuerProfile.objects.filter(owner=request.user).first()
        if not profile:
            return Response(None)
        return Response(IssuerProfileSerializer(profile).data)

    def put(self, request):
        profile = IssuerProfile.objects.filter(owner=request.user).first()
        if profile:
            serializer = IssuerProfileSerializer(profile, data=request.data)
        else:
            serializer = IssuerProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(owner=request.user)
        return Response(serializer.data)


class ClientViewSet(viewsets.ModelViewSet):
    serializer_class = ClientSerializer

    def get_queryset(self):
        return Client.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer
    parser_classes = [MultiPartParser, FormParser]
    filterset_fields = ["kind", "client"]
    search_fields = ["title", "original_filename", "notes"]
    ordering_fields = ["document_date", "created_at", "title", "kind"]
    ordering = ["-document_date", "-created_at"]

    def get_queryset(self):
        qs = Document.objects.filter(owner=self.request.user).select_related("client")
        scope = self.request.query_params.get("scope")
        if scope == "personal":
            qs = qs.filter(client__isnull=True)
        elif scope == "client":
            qs = qs.filter(client__isnull=False)
        return qs

    def perform_create(self, serializer):
        file_obj = self.request.FILES.get("file")
        if not file_obj:
            raise ValidationError({"file": "File is required."})
        title = serializer.validated_data.get("title") or Path(file_obj.name).stem
        serializer.save(
            owner=self.request.user,
            title=title,
            original_filename=file_obj.name,
        )

    def perform_update(self, serializer):
        file_obj = self.request.FILES.get("file")
        extras = {}
        if file_obj:
            extras["original_filename"] = file_obj.name
        serializer.save(**extras)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        doc = self.get_object()
        if not doc.file:
            raise ValidationError({"detail": "No file on this document."})
        filename = doc.original_filename or Path(doc.file.name).name
        return FileResponse(doc.file.open("rb"), as_attachment=True, filename=filename)


class ReceiptViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ReceiptSerializer
    filterset_fields = ["kind"]

    def get_queryset(self):
        return (
            Receipt.objects.filter(owner=self.request.user)
            .select_related("transaction")
            .prefetch_related("items__tags")
        )

    def perform_update(self, serializer):
        receipt = serializer.save()
        try_match_receipt(receipt)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        receipt = self.get_object()
        if not receipt.file:
            raise ValidationError({"detail": "No file on this receipt."})
        filename = receipt.original_filename or Path(receipt.file.name).name
        return FileResponse(receipt.file.open("rb"), filename=filename)

    @action(detail=True, methods=["get"])
    def matches(self, request, pk=None):
        receipt = self.get_object()
        hits = candidate_transactions(
            request.user,
            receipt.amount,
            receipt.document_date,
            receipt.currency,
            limit=20,
            days=window_days(receipt),
        )
        return Response(
            TransactionSerializer(hits, many=True, context={"request": request}).data
        )

    @action(detail=True, methods=["post"])
    def attach(self, request, pk=None):
        receipt = self.get_object()
        tx = Transaction.objects.filter(
            owner=request.user, id=request.data.get("transaction")
        ).first()
        if tx is None:
            raise ValidationError({"transaction": "Not found."})
        if receipt.amount is None:
            receipt.amount = abs(tx.amount)
            receipt.currency = tx.currency or receipt.currency or "EUR"
            receipt.save(update_fields=["amount", "currency"])
        link_receipt(receipt, tx)
        receipt = self.get_queryset().get(pk=receipt.pk)
        return Response(self.get_serializer(receipt).data)


class PurchaseItemViewSet(mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = PurchaseItemSerializer

    def get_queryset(self):
        return PurchaseItem.objects.filter(receipt__owner=self.request.user).prefetch_related(
            "tags"
        )

    @action(detail=True, methods=["post"])
    def tag(self, request, pk=None):
        item = self.get_object()
        add_ids = request.data.get("add") or []
        remove_ids = {int(i) for i in (request.data.get("remove") or [])}
        tags = {t.id: t for t in item.tags.all() if t.id not in remove_ids}
        for tag in Tag.objects.filter(owner=request.user, id__in=add_ids):
            tags[tag.id] = tag
        set_item_tags(item, tags.values())
        item = self.get_queryset().get(pk=item.pk)
        return Response(self.get_serializer(item).data)


class InvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    filterset_fields = ["status", "client", "service_year", "service_month"]
    search_fields = ["number", "description", "client_name"]
    ordering_fields = [
        "issue_date",
        "sale_date",
        "number",
        "total_amount",
        "service_year",
        "service_month",
    ]
    ordering = ["-issue_date", "-id"]

    def get_queryset(self):
        return Invoice.objects.filter(owner=self.request.user).select_related(
            "client", "account"
        )

    def _guard_mutable(self, invoice: Invoice):
        if invoice.is_issued:
            raise ValidationError(
                {"detail": "Issued invoices are immutable. Create a new draft instead."}
            )

    def perform_create(self, serializer):
        issue_date = serializer.validated_data.get("issue_date") or dt.date.today()
        number = (serializer.validated_data.get("number") or "").strip() or (
            invoicing.suggest_number(self.request.user, issue_date)
        )
        invoice = serializer.save(
            owner=self.request.user,
            status=Invoice.STATUS_DRAFT,
            number=number,
        )
        self._prepare_draft(invoice, serializer.validated_data)
        invoice.save()

    def perform_update(self, serializer):
        self._guard_mutable(serializer.instance)
        invoice = serializer.save()
        self._prepare_draft(invoice, serializer.validated_data)
        invoice.save()

    def perform_destroy(self, instance):
        self._guard_mutable(instance)
        instance.delete()

    def _prepare_draft(self, invoice: Invoice, data: dict):
        if not invoice.account_id:
            invoice.account = invoicing.default_invoice_account(invoice.owner)
        client = invoice.client if invoice.client_id else None
        if client and not data.get("description") and not invoice.description:
            invoice.description = client.default_description
        if client and "unit_price" not in data and invoice.unit_price in (None, 0):
            invoice.unit_price = client.default_unit_price
        if client and "currency" not in data:
            invoice.currency = client.currency or invoice.currency
        if not invoice.number:
            invoice.number = invoicing.suggest_number(invoice.owner, invoice.issue_date)
        invoicing.apply_snapshots(invoice)
        invoice.recalculate_amounts()

    @action(detail=False, methods=["get"])
    def advise(self, request):
        try:
            year = int(request.query_params["year"])
            month = int(request.query_params["month"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValidationError(
                {"detail": "Query params 'year' and 'month' are required."}
            ) from exc
        if month < 1 or month > 12:
            raise ValidationError({"detail": "month must be 1–12."})
        hours_per_day = int(request.query_params.get("hours_per_day", 8))
        advice = invoicing.advise_hours(year, month, hours_per_day=hours_per_day)
        unit_price = request.query_params.get("unit_price")
        if unit_price is not None:
            from decimal import Decimal

            price = Decimal(unit_price)
            advice["unit_price"] = str(price)
            advice["suggested_net"] = str(
                (Decimal(advice["suggested_hours"]) * price).quantize(Decimal("0.01"))
            )
        issue = dt.date.today()
        advice["suggested_issue_date"] = issue.isoformat()
        advice["suggested_due_date"] = (issue + dt.timedelta(days=14)).isoformat()
        advice["suggested_number"] = invoicing.suggest_number(request.user, issue)
        return Response(advice)

    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        invoice = self.get_object()
        self._guard_mutable(invoice)
        if not IssuerProfile.objects.filter(owner=request.user).exists():
            raise ValidationError(
                {"detail": "Set your issuer profile before issuing an invoice."}
            )
        if not invoice.account_id and not invoicing.default_invoice_account(request.user):
            raise ValidationError(
                {"detail": "Select a bank account (with IBAN) before issuing."}
            )
        try:
            invoicing.issue_invoice(invoice)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(self.get_serializer(invoice).data)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        invoice = self.get_object()
        # Use `kind`, not `format` — DRF reserves `format` for content negotiation.
        kind = request.query_params.get("kind", "pdf")
        if kind not in ("pdf", "xlsx"):
            raise ValidationError({"detail": "kind must be 'pdf' or 'xlsx'."})
        # Always render from snapshotted invoice fields so font/layout fixes
        # apply to older issued invoices without mutating their data.
        if invoice.status != Invoice.STATUS_ISSUED:
            invoicing.apply_snapshots(invoice)
            invoice.recalculate_amounts()
        content = (
            invoicing.build_pdf(invoice)
            if kind == "pdf"
            else invoicing.build_xlsx(invoice)
        )
        content_type = (
            "application/pdf"
            if kind == "pdf"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = (
            f'attachment; filename="invoice-{invoice.number}.{kind}"'
        )
        return response

    @action(detail=False, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def import_xlsx(self, request):
        file_obj = request.FILES.get("file")
        if not file_obj:
            raise ValidationError({"detail": "No file provided (form field 'file')."})
        client_id = request.data.get("client")
        client = Client.objects.filter(owner=request.user, id=client_id).first()
        if not client:
            raise ValidationError({"detail": "client id is required."})

        suffix = Path(file_obj.name).suffix or ".xlsx"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            for chunk in file_obj.chunks():
                tmp.write(chunk)
            tmp_path = Path(tmp.name)
        try:
            parsed = invoicing.parse_invoice_xlsx(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        if not parsed["issue_date"] or not parsed["sale_date"]:
            raise ValidationError(
                {"detail": "Could not determine issue/sale dates from the file."}
            )

        number = parsed["number"]
        if Invoice.objects.filter(owner=request.user, number=number).exists():
            raise ValidationError({"detail": f"Invoice #{number} already exists."})

        account = invoicing.default_invoice_account(request.user)
        invoice = Invoice(
            owner=request.user,
            status=Invoice.STATUS_DRAFT,
            number=number,
            client=client,
            account=account,
            service_year=parsed["sale_date"].year,
            service_month=parsed["sale_date"].month,
            issue_date=parsed["issue_date"],
            sale_date=parsed["sale_date"],
            due_date=parsed["due_date"] or parsed["issue_date"] + dt.timedelta(days=14),
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
        invoice.issued_at = timezone.now()
        invoice.save()
        return Response(self.get_serializer(invoice).data, status=status.HTTP_201_CREATED)


class TagViewSet(viewsets.ModelViewSet):
    serializer_class = TagSerializer

    def get_queryset(self):
        return Tag.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["get"])
    def transactions(self, request, pk=None):
        tag = self.get_object()
        qs = tag.transactions.all().order_by("-operation_date", "-id")
        page = self.paginate_queryset(qs)
        serializer = TransactionSerializer(page or qs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class BudgetViewSet(viewsets.ModelViewSet):
    serializer_class = BudgetSerializer

    def get_queryset(self):
        return Budget.objects.filter(owner=self.request.user).select_related(
            "tag", "account"
        )

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=False, methods=["get"])
    def status(self, request):
        from .budgets import status as budget_status
        from .criteria import view_window
        from .tax import estimate

        estimate(request.user)

        try:
            start, end = view_window(
                year=request.query_params.get("year"),
                month=request.query_params.get("month"),
                quarter=request.query_params.get("quarter"),
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise ValidationError(
                {"detail": "year, month, and quarter must be numbers."}
            ) from exc
        return Response(budget_status(request.user, start, end))


class RecurrenceViewSet(viewsets.ModelViewSet):
    serializer_class = RecurrenceSerializer

    def get_queryset(self):
        return Recurrence.objects.filter(owner=self.request.user).prefetch_related(
            "tags", "occurrences"
        )

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        recs = getattr(self, "_stats_recs", None)
        if recs is not None:
            from .recurrences import stats_map

            ctx["stats"] = stats_map(recs)
        return ctx

    def list(self, request, *args, **kwargs):
        from .tax import estimate

        estimate(request.user)
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        recs = list(page if page is not None else qs)
        self._stats_recs = recs
        serializer = self.get_serializer(recs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        rec = self.get_object()
        self._stats_recs = [rec]
        return Response(self.get_serializer(rec).data)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=False, methods=["post"])
    def from_transaction(self, request):
        from .recurrences import seed_from_transaction

        ser = FromTransactionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        tx = Transaction.objects.filter(
            owner=request.user, id=data["transaction_id"]
        ).first()
        if tx is None:
            raise ValidationError({"transaction_id": "Unknown transaction."})
        overrides = {
            k: v
            for k, v in data.items()
            if k != "transaction_id" and v is not None and v != ""
        }
        if "tags" in overrides:
            overrides["tags"] = Tag.objects.filter(
                owner=request.user, id__in=overrides["tags"]
            )
        rec = seed_from_transaction(tx, **overrides)
        rec = self.get_queryset().get(pk=rec.pk)
        self._stats_recs = [rec]
        return Response(self.get_serializer(rec).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def forecast(self, request):
        from .recurrences import forecast

        recs = list(self.get_queryset())
        return Response(forecast(request.user, recs))

    @action(detail=True, methods=["get"])
    def transactions(self, request, pk=None):
        rec = self.get_object()
        qs = (
            Transaction.objects.filter(owner=request.user, recurrence=rec)
            .select_related("account", "recurrence")
            .prefetch_related("tag_links__tag")
        )
        page = self.paginate_queryset(qs)
        ser = TransactionSerializer(
            page if page is not None else qs, many=True, context={"request": request}
        )
        if page is not None:
            return self.get_paginated_response(ser.data)
        return Response(ser.data)

    @action(detail=True, methods=["get"])
    def suggest(self, request, pk=None):
        from .recurrences import suggest

        rec = self.get_object()
        txs = suggest(rec)
        return Response(
            TransactionSerializer(txs, many=True, context={"request": request}).data
        )

    @action(detail=True, methods=["post"])
    def attach(self, request, pk=None):
        from .recurrences import attach, detach

        rec = self.get_object()
        ser = RecurrenceAttachSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ids = ser.validated_data["transaction_ids"]
        do_detach = ser.validated_data.get("detach")
        txs = list(
            Transaction.objects.filter(owner=request.user, id__in=ids).prefetch_related(
                "tag_links"
            )
        )
        rec = Recurrence.objects.prefetch_related("tags").get(pk=rec.pk)
        changed = 0
        for tx in txs:
            if do_detach:
                detach(tx, rec)
                changed += 1
            elif tx.recurrence_id in (None, rec.id):
                if attach(tx, rec):
                    changed += 1
        rec = self.get_queryset().get(pk=rec.pk)
        self._stats_recs = [rec]
        return Response(
            {"updated": changed, "recurrence": self.get_serializer(rec).data}
        )


class TaxProfileView(APIView):
    """GET/PATCH the current user's autónomo tax settings."""

    def get(self, request):
        from .tax import get_or_create_profile

        profile = get_or_create_profile(request.user)
        return Response(TaxProfileSerializer(profile, context={"request": request}).data)

    def patch(self, request):
        from .tax import get_or_create_profile

        profile = get_or_create_profile(request.user)
        serializer = TaxProfileSerializer(
            profile, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def put(self, request):
        return self.patch(request)


class TaxEstimateView(APIView):
    """GET year estimate: current + planned income vs remaining tax."""

    def get(self, request):
        from .tax import estimate

        raw = request.query_params.get("year")
        year = None
        if raw:
            try:
                year = int(raw)
            except ValueError as exc:
                raise ValidationError({"year": "Use a calendar year."}) from exc
        return Response(estimate(request.user, year))


class RuleViewSet(viewsets.ModelViewSet):
    serializer_class = RuleSerializer

    def get_queryset(self):
        return Rule.objects.filter(owner=self.request.user).prefetch_related("tags")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=False, methods=["post"])
    def apply(self, request):
        ids = request.data.get("transaction_ids")
        qs = Transaction.objects.filter(owner=request.user)
        if ids:
            qs = qs.filter(id__in=ids)
        result = apply_rules(request.user, qs)
        return Response(result)

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        rule = self.get_object()
        base = Transaction.objects.filter(owner=request.user)
        matches = apply_criteria(base, rule.criteria)
        if rule.regex:
            import re

            try:
                pattern = re.compile(rule.regex, re.IGNORECASE)
                keep = [
                    t.id
                    for t in matches.only("id", "concept")
                    if pattern.search(t.concept or "")
                ]
                matches = base.filter(id__in=keep)
            except re.error:
                return Response(
                    {"detail": "Invalid regex."}, status=status.HTTP_400_BAD_REQUEST
                )
        sample = matches.order_by("-operation_date")[:10]
        return Response(
            {
                "match_count": matches.count(),
                "sample": TransactionSerializer(sample, many=True).data,
            }
        )


class FolderViewSet(viewsets.ModelViewSet):
    serializer_class = FolderSerializer

    def get_queryset(self):
        return Folder.objects.filter(owner=self.request.user).prefetch_related(
            "tags", "children"
        )

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def perform_update(self, serializer):
        parent = serializer.validated_data.get("parent", serializer.instance.parent)
        self._guard_cycle(serializer.instance, parent)
        serializer.save()

    def _guard_cycle(self, folder, parent):
        if parent is None:
            return
        if parent.id == folder.id:
            raise ValidationError("A folder cannot be its own parent.")
        descendant_ids = {d.id for d in descendants(folder)}
        if parent.id in descendant_ids:
            raise ValidationError("Cannot move a folder into its own descendant.")

    @action(detail=False, methods=["get"])
    def tree(self, request):
        folders = list(self.get_queryset())
        by_parent = defaultdict(list)
        for f in folders:
            by_parent[f.parent_id].append(f)

        context = self.get_serializer_context()

        def build(node):
            data = FolderSerializer(node, context=context).data
            data["children"] = [build(child) for child in by_parent.get(node.id, [])]
            return data

        return Response([build(root) for root in by_parent.get(None, [])])

    @action(detail=True, methods=["get"])
    def transactions(self, request, pk=None):
        folder = self.get_object()
        recursive = request.query_params.get("recursive", "true").lower() != "false"
        ids = folder_transaction_ids(folder, recursive=recursive)
        qs = (
            Transaction.objects.filter(id__in=ids)
            .prefetch_related("tag_links__tag")
            .order_by("-operation_date", "-id")
        )
        page = self.paginate_queryset(qs)
        serializer = TransactionSerializer(page or qs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="update-transactions")
    def update_transactions(self, request, pk=None):
        folder = self.get_object()
        serializer = FolderTransactionsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        add_ids = serializer.validated_data["add"]
        remove_ids = serializer.validated_data["remove"]

        owned = Transaction.objects.filter(owner=request.user)
        if add_ids:
            to_add = list(owned.filter(id__in=add_ids))
            folder.included_transactions.add(*to_add)
            folder.excluded_transactions.remove(*to_add)
        if remove_ids:
            to_remove = list(owned.filter(id__in=remove_ids))
            folder.excluded_transactions.add(*to_remove)
            folder.included_transactions.remove(*to_remove)

        return Response(
            {
                "id": folder.id,
                "transaction_count": len(folder_transaction_ids(folder, recursive=True)),
            }
        )

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        folder = self.get_object()
        totals = request.query_params.get("totals", "both")
        if totals not in ("income", "expense", "both"):
            totals = "both"
        recursive = request.query_params.get("recursive", "true").lower() != "false"

        def sheet_for(f):
            qs = Transaction.objects.filter(id__in=own_transaction_ids(f)).order_by(
                "operation_date", "id"
            )
            return (f.name, qs)

        if recursive:
            # One sheet per folder in the subtree (parent + descendants) that has
            # its own transactions, so child folders export as separate sheets.
            sheets = [sheet_for(f) for f in subtree(folder) if own_transaction_ids(f)]
            if not sheets:
                sheets = [(folder.name, Transaction.objects.none())]
        else:
            sheets = [sheet_for(folder)]

        buffer = build_workbook(sheets, totals=totals)
        safe_name = "".join(
            c for c in folder.name if c.isalnum() or c in (" ", "-", "_")
        ).strip().replace(" ", "_") or "folder"
        stamp = dt.date.today().isoformat()
        filename = f"{safe_name}_{stamp}.xlsx"
        response = FileResponse(
            buffer,
            as_attachment=True,
            filename=filename,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        return response


class AiViewSet(viewsets.ViewSet):
    @action(detail=False, methods=["post"])
    def classify(self, request):
        serializer = AiClassifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        qs = Transaction.objects.filter(owner=request.user).prefetch_related(
            "tag_links"
        )
        if data["transaction_ids"]:
            qs = qs.filter(id__in=data["transaction_ids"])
        elif data["scope"] == "untagged":
            qs = qs.filter(tag_links__isnull=True)
        qs = qs.order_by("-operation_date", "-id")[: data["limit"]]

        transactions = list(qs)
        if not transactions:
            return Response({"suggestions": []})

        try:
            raw = ai.classify(request.user, transactions)
        except ai.AiNotConfigured as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001 - surface provider errors
            return Response(
                {"detail": f"AI classification failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        tag_names = dict(
            Tag.objects.filter(owner=request.user).values_list("id", "name")
        )
        tx_by_id = {tx.id: tx for tx in transactions}
        suggestions = []
        for item in raw:
            tx = tx_by_id.get(item.get("transaction_id"))
            if tx is None:
                continue
            valid_tag_ids = [t for t in item.get("tag_ids", []) if t in tag_names]
            suggestions.append(
                {
                    "transaction_id": tx.id,
                    "concept": tx.concept,
                    "counterparty": tx.counterparty,
                    "amount": tx.amount,
                    "tag_ids": valid_tag_ids,
                    "tag_names": [tag_names[t] for t in valid_tag_ids],
                    "new_tags": item.get("new_tags", []),
                    "confidence": item.get("confidence"),
                }
            )
        return Response({"suggestions": suggestions})

    @action(detail=False, methods=["post"])
    def apply(self, request):
        serializer = AiApplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data["items"]

        owned_tx = set(
            Transaction.objects.filter(owner=request.user).values_list("id", flat=True)
        )
        created = 0
        new_tags_created = 0
        for item in items:
            tx_id = item["transaction_id"]
            if tx_id not in owned_tx:
                continue
            tag_ids = list(item["tag_ids"])
            for name in item["new_tags"]:
                name = name.strip()
                if not name:
                    continue
                tag, was_new = Tag.objects.get_or_create(
                    owner=request.user, name=name
                )
                if was_new:
                    new_tags_created += 1
                tag_ids.append(tag.id)

            valid_tags = Tag.objects.filter(owner=request.user, id__in=tag_ids)
            for tag in valid_tags:
                _, was_created = TransactionTag.objects.get_or_create(
                    transaction_id=tx_id,
                    tag=tag,
                    defaults={
                        "source": TransactionTag.SOURCE_AI,
                        "confidence": item.get("confidence"),
                    },
                )
                if was_created:
                    created += 1

        return Response(
            {"assignments_created": created, "new_tags_created": new_tags_created}
        )


# Models included in a backup, in dependency order for restore.
BACKUP_MODELS = [
    Account,
    IssuerProfile,
    Client,
    Document,
    Tag,
    Budget,
    Rule,
    Recurrence,
    TaxProfile,
    Upload,
    Transaction,
    TransactionTag,
    Folder,
    Invoice,
    Receipt,
    PurchaseItem,
]


class BackupExportView(APIView):
    """Download all of the current user's data as a Django fixture JSON."""

    def get(self, request):
        user = request.user
        querysets = [
            Account.objects.filter(owner=user),
            IssuerProfile.objects.filter(owner=user),
            Client.objects.filter(owner=user),
            Document.objects.filter(owner=user),
            Tag.objects.filter(owner=user),
            Budget.objects.filter(owner=user),
            Rule.objects.filter(owner=user),
            Recurrence.objects.filter(owner=user),
            TaxProfile.objects.filter(owner=user),
            Upload.objects.filter(owner=user),
            Transaction.objects.filter(owner=user),
            TransactionTag.objects.filter(transaction__owner=user),
            Folder.objects.filter(owner=user),
            Invoice.objects.filter(owner=user),
            Receipt.objects.filter(owner=user),
            PurchaseItem.objects.filter(receipt__owner=user),
        ]
        objects = [obj for qs in querysets for obj in qs]
        data = dj_serializers.serialize("json", objects, indent=2)

        stamp = dt.date.today().isoformat()
        response = HttpResponse(data, content_type="application/json")
        response["Content-Disposition"] = (
            f'attachment; filename="income-share-backup-{stamp}.json"'
        )
        return response


class BackupImportView(APIView):
    """Restore a backup, replacing all of the current user's data."""

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response(
                {"detail": "No file provided (expected form field 'file')."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            payload = file_obj.read().decode("utf-8")
            objects = list(dj_serializers.deserialize("json", payload, ignorenonexistent=True))
        except Exception as exc:  # noqa: BLE001 - surface parse errors to the client
            return Response(
                {"detail": f"Invalid backup file: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        try:
            with db_transaction.atomic():
                # Deleting transactions/uploads cascades their tag links.
                PurchaseItem.objects.filter(receipt__owner=user).delete()
                Receipt.objects.filter(owner=user).delete()
                Invoice.objects.filter(owner=user).delete()
                Folder.objects.filter(owner=user).delete()
                Rule.objects.filter(owner=user).delete()
                Transaction.objects.filter(owner=user).delete()
                Recurrence.objects.filter(owner=user).delete()
                TaxProfile.objects.filter(owner=user).delete()
                Upload.objects.filter(owner=user).delete()
                Budget.objects.filter(owner=user).delete()
                Tag.objects.filter(owner=user).delete()
                Document.objects.filter(owner=user).delete()
                Client.objects.filter(owner=user).delete()
                IssuerProfile.objects.filter(owner=user).delete()
                Account.objects.filter(owner=user).delete()

                counts = defaultdict(int)
                for obj in objects:
                    instance = obj.object
                    if hasattr(instance, "owner_id"):
                        instance.owner_id = user.id
                    obj.save()
                    counts[instance._meta.model_name] += 1

            sql = connection.ops.sequence_reset_sql(no_style(), BACKUP_MODELS)
            if sql:
                with connection.cursor() as cursor:
                    for statement in sql:
                        cursor.execute(statement)
        except Exception as exc:  # noqa: BLE001 - restore is all-or-nothing
            return Response(
                {"detail": f"Restore failed: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"restored": dict(counts)})
