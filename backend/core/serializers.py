from decimal import Decimal
import datetime as dt

from rest_framework import serializers

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


class OwnerScopedPKField(serializers.PrimaryKeyRelatedField):
    """PrimaryKeyRelatedField whose queryset is limited to the request user."""

    def __init__(self, model, **kwargs):
        self._model = model
        super().__init__(queryset=model.objects.none(), **kwargs)

    def get_queryset(self):
        request = self.context.get("request")
        qs = self._model.objects.all()
        if request is not None and request.user.is_authenticated:
            qs = qs.filter(owner=request.user)
        return qs


class AccountSerializer(serializers.ModelSerializer):
    transaction_count = serializers.IntegerField(
        source="transactions.count", read_only=True
    )
    effective_balance = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )

    class Meta:
        model = Account
        fields = [
            "id",
            "name",
            "kind",
            "bank",
            "iban",
            "bic",
            "correspondent_bic",
            "bank_address",
            "currency",
            "balance",
            "credit_limit",
            "effective_balance",
            "group",
            "is_default",
            "is_invoice_default",
            "transaction_count",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "transaction_count",
            "effective_balance",
            "created_at",
        ]

    def validate(self, attrs):
        kind = attrs.get("kind") or getattr(self.instance, "kind", Account.KIND_BANK)
        if kind != Account.KIND_BANK:
            attrs["is_default"] = False
            attrs["is_invoice_default"] = False
        limit = attrs.get("credit_limit", getattr(self.instance, "credit_limit", None))
        if limit is not None and limit <= 0:
            attrs["credit_limit"] = None
        return attrs


class TransferSerializer(serializers.Serializer):
    from_account = OwnerScopedPKField(model=Account)
    to_account = OwnerScopedPKField(model=Account)
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.01")
    )
    operation_date = serializers.DateField()
    concept = serializers.CharField(required=False, allow_blank=True, max_length=255)

    def validate(self, attrs):
        src, dst = attrs["from_account"], attrs["to_account"]
        if src.pk == dst.pk:
            raise serializers.ValidationError("Pick two different accounts.")
        if (src.currency or "").upper() != (dst.currency or "").upper():
            raise serializers.ValidationError("Accounts must share a currency.")
        return attrs


class IssuerProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = IssuerProfile
        fields = [
            "id",
            "legal_name",
            "trade_name",
            "vat_number",
            "address",
            "city",
            "country",
            "phone",
            "email",
            "legal_form",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = [
            "id",
            "name",
            "tax_id",
            "address",
            "vat_mode",
            "default_vat_rate",
            "default_description",
            "default_unit_price",
            "currency",
            "notes",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class DocumentSerializer(serializers.ModelSerializer):
    client = OwnerScopedPKField(model=Client, required=False, allow_null=True)
    client_label = serializers.CharField(source="client.name", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "id",
            "client",
            "client_label",
            "kind",
            "kind_label",
            "title",
            "document_date",
            "notes",
            "original_filename",
            "file",
            "file_url",
            "created_at",
        ]
        read_only_fields = ["id", "original_filename", "file_url", "created_at"]
        extra_kwargs = {
            "file": {"required": False},
            "notes": {"required": False, "allow_blank": True},
            "document_date": {"required": False, "allow_null": True},
        }

    def get_file_url(self, obj):
        if not obj.file:
            return None
        request = self.context.get("request")
        url = obj.file.url
        return request.build_absolute_uri(url) if request else url

    def to_internal_value(self, data):
        # Multipart forms send client="" for personal docs.
        if hasattr(data, "copy"):
            data = data.copy()
            if data.get("client") in ("", None):
                data["client"] = None
        return super().to_internal_value(data)


class InvoiceSerializer(serializers.ModelSerializer):
    client = OwnerScopedPKField(model=Client)
    account = OwnerScopedPKField(model=Account, required=False, allow_null=True)
    client_label = serializers.CharField(source="client.name", read_only=True)
    account_label = serializers.CharField(source="account.name", read_only=True)
    is_issued = serializers.BooleanField(read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "status",
            "number",
            "client",
            "client_label",
            "account",
            "account_label",
            "service_year",
            "service_month",
            "issue_date",
            "sale_date",
            "due_date",
            "description",
            "quantity",
            "unit_price",
            "currency",
            "vat_rate",
            "vat_label",
            "net_amount",
            "vat_amount",
            "total_amount",
            "notes",
            "issuer_name",
            "issuer_trade_name",
            "issuer_vat_number",
            "issuer_address",
            "issuer_city",
            "issuer_country",
            "issuer_phone",
            "issuer_email",
            "issuer_legal_form",
            "client_name",
            "client_tax_id",
            "client_address",
            "vat_mode",
            "account_name",
            "bank_name",
            "iban",
            "bic",
            "correspondent_bic",
            "bank_address",
            "xlsx_file",
            "pdf_file",
            "issued_at",
            "is_issued",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "net_amount",
            "vat_amount",
            "total_amount",
            "issuer_name",
            "issuer_trade_name",
            "issuer_vat_number",
            "issuer_address",
            "issuer_city",
            "issuer_country",
            "issuer_phone",
            "issuer_email",
            "issuer_legal_form",
            "client_name",
            "client_tax_id",
            "client_address",
            "vat_mode",
            "account_name",
            "bank_name",
            "iban",
            "bic",
            "correspondent_bic",
            "bank_address",
            "xlsx_file",
            "pdf_file",
            "issued_at",
            "is_issued",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "number": {"required": False, "allow_blank": True},
            "account": {"required": False, "allow_null": True},
            "notes": {"required": False, "allow_blank": True},
            "vat_rate": {"required": False},
            "vat_label": {"required": False, "allow_blank": True},
        }


class UploadSerializer(serializers.ModelSerializer):
    account_label = serializers.CharField(source="account.name", read_only=True)

    class Meta:
        model = Upload
        fields = [
            "id",
            "original_filename",
            "account",
            "account_label",
            "account_name",
            "account_iban",
            "account_holder",
            "currency",
            "row_count",
            "imported_count",
            "parsed_at",
            "created_at",
        ]
        read_only_fields = fields


class TagSerializer(serializers.ModelSerializer):
    transaction_count = serializers.IntegerField(
        source="transactions.count", read_only=True
    )

    class Meta:
        model = Tag
        fields = [
            "id",
            "name",
            "color",
            "description",
            "ignore_stats",
            "transaction_count",
            "created_at",
        ]
        read_only_fields = ["id", "transaction_count", "created_at"]


class BudgetSerializer(serializers.ModelSerializer):
    tag = OwnerScopedPKField(model=Tag)
    account = OwnerScopedPKField(model=Account, required=False, allow_null=True)
    tag_name = serializers.CharField(source="tag.name", read_only=True)
    tag_color = serializers.CharField(source="tag.color", read_only=True)
    account_label = serializers.CharField(
        source="account.name", read_only=True, default=None
    )

    class Meta:
        model = Budget
        fields = [
            "id",
            "tag",
            "tag_name",
            "tag_color",
            "account",
            "account_label",
            "period",
            "kind",
            "amount",
            "is_active",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "tag_name",
            "tag_color",
            "account_label",
            "created_at",
        ]


class RecurrenceSerializer(serializers.ModelSerializer):
    account = OwnerScopedPKField(model=Account, required=False, allow_null=True)
    tags = OwnerScopedPKField(model=Tag, many=True, required=False)
    account_label = serializers.CharField(
        source="account.name", read_only=True, default=None
    )
    next_due = serializers.SerializerMethodField()
    last_date = serializers.SerializerMethodField()
    occurrence_count = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    next_month_count = serializers.SerializerMethodField()
    next_month_remaining = serializers.SerializerMethodField()
    next_month_remaining_eur = serializers.SerializerMethodField()

    class Meta:
        model = Recurrence
        fields = [
            "id",
            "name",
            "amount",
            "currency",
            "frequency",
            "due_day",
            "start_date",
            "end_date",
            "account",
            "account_label",
            "match_text",
            "amount_tolerance_pct",
            "auto_match",
            "category",
            "is_active",
            "tags",
            "next_due",
            "last_date",
            "occurrence_count",
            "status",
            "next_month_count",
            "next_month_remaining",
            "next_month_remaining_eur",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "account_label",
            "next_due",
            "last_date",
            "occurrence_count",
            "status",
            "next_month_count",
            "next_month_remaining",
            "next_month_remaining_eur",
            "created_at",
        ]

    def validate(self, attrs):
        freq = attrs.get("frequency") or getattr(
            self.instance, "frequency", Recurrence.FREQ_MONTH
        )
        due = attrs.get("due_day")
        if due is None:
            due = getattr(self.instance, "due_day", 1)
        due = int(due)
        if freq == Recurrence.FREQ_WEEK:
            if not 0 <= due <= 6:
                raise serializers.ValidationError(
                    {"due_day": "Weekday must be 0–6 (Mon–Sun)."}
                )
        elif not 1 <= due <= 31:
            raise serializers.ValidationError({"due_day": "Day of month must be 1–31."})
        return attrs

    def _stat(self, obj, key):
        stats = (self.context or {}).get("stats") or {}
        row = stats.get(obj.id)
        if row is not None:
            return row.get(key)
        from .recurrences import last_paid, next_unpaid, status_for

        live = {
            "occurrence_count": obj.occurrences.count(),
            "last_date": last_paid(obj),
            "next_due": next_unpaid(obj),
            "status": status_for(obj),
        }
        return live.get(key)

    def get_next_due(self, obj):
        value = self._stat(obj, "next_due")
        return value.isoformat() if hasattr(value, "isoformat") else value

    def get_last_date(self, obj):
        value = self._stat(obj, "last_date")
        return value.isoformat() if hasattr(value, "isoformat") else value

    def get_occurrence_count(self, obj):
        return self._stat(obj, "occurrence_count") or 0

    def get_status(self, obj):
        return self._stat(obj, "status")

    def get_next_month_count(self, obj):
        return self._stat(obj, "next_month_count") or 0

    def get_next_month_remaining(self, obj):
        value = self._stat(obj, "next_month_remaining")
        return 0 if value is None else value

    def get_next_month_remaining_eur(self, obj):
        return self._stat(obj, "next_month_remaining_eur")


class FromTransactionSerializer(serializers.Serializer):
    transaction_id = serializers.IntegerField()
    name = serializers.CharField(required=False, allow_blank=True, max_length=120)
    frequency = serializers.ChoiceField(
        choices=Recurrence.FREQ_CHOICES, required=False
    )
    category = serializers.ChoiceField(
        choices=Recurrence.CAT_CHOICES, required=False
    )
    due_day = serializers.IntegerField(required=False)
    amount_tolerance_pct = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False
    )
    auto_match = serializers.BooleanField(required=False)
    tags = serializers.ListField(
        child=serializers.IntegerField(), required=False
    )


class RecurrenceAttachSerializer(serializers.Serializer):
    transaction_ids = serializers.ListField(child=serializers.IntegerField())
    detach = serializers.BooleanField(required=False, default=False)


class TaxProfileSerializer(serializers.ModelSerializer):
    deductible_tags = OwnerScopedPKField(model=Tag, many=True, required=False)

    class Meta:
        model = TaxProfile
        fields = [
            "id",
            "irpf_method",
            "withholding_rate",
            "simplificada",
            "income_from",
            "hourly_rate",
            "hours_per_day",
            "hours_overrides",
            "ss_mode",
            "ss_cuota_override",
            "new_autonomo_start",
            "planned_income_override",
            "deductible_tags",
            "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]

    def validate_hours_overrides(self, value):
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("Must be an object of YYYY-MM → hours.")
        clean = {}
        for key, hours in value.items():
            token = str(key).strip()
            if len(token) != 7 or token[4] != "-":
                raise serializers.ValidationError(f"Bad month key {key!r}.")
            try:
                year, month = int(token[:4]), int(token[5:])
            except ValueError as exc:
                raise serializers.ValidationError(f"Bad month key {key!r}.") from exc
            if month < 1 or month > 12:
                raise serializers.ValidationError(f"Bad month key {key!r}.")
            if hours in (None, ""):
                continue
            clean[f"{year:04d}-{month:02d}"] = float(hours)
        return clean


class TransactionTagSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="tag.id", read_only=True)
    name = serializers.CharField(source="tag.name", read_only=True)
    color = serializers.CharField(source="tag.color", read_only=True)

    class Meta:
        model = TransactionTag
        fields = ["id", "name", "color", "source", "confidence"]


class TransactionSerializer(serializers.ModelSerializer):
    kind = serializers.CharField(read_only=True)
    pending = serializers.BooleanField(read_only=True)
    tags = TransactionTagSerializer(source="tag_links", many=True, read_only=True)
    account_label = serializers.CharField(source="account.name", read_only=True)
    receipt_id = serializers.SerializerMethodField()
    receipt_kind = serializers.SerializerMethodField()
    item_count = serializers.SerializerMethodField()
    recurrence = serializers.IntegerField(
        source="recurrence_id", read_only=True, allow_null=True
    )
    recurrence_name = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            "id",
            "operation_date",
            "value_date",
            "concept",
            "counterparty",
            "amount",
            "balance",
            "currency",
            "kind",
            "pending",
            "tags",
            "metadata",
            "upload",
            "account",
            "account_label",
            "receipt_id",
            "receipt_kind",
            "item_count",
            "recurrence",
            "recurrence_name",
            "created_at",
        ]
        read_only_fields = fields

    def get_receipt_id(self, obj):
        return getattr(obj, "receipt_id", None)

    def get_receipt_kind(self, obj):
        return getattr(obj, "receipt_kind", None)

    def get_item_count(self, obj):
        return getattr(obj, "item_count", 0) or 0

    def get_recurrence_name(self, obj):
        rec = getattr(obj, "recurrence", None)
        return rec.name if rec else None


class RuleSerializer(serializers.ModelSerializer):
    tags = OwnerScopedPKField(model=Tag, many=True, required=False)

    class Meta:
        model = Rule
        fields = [
            "id",
            "name",
            "order",
            "is_active",
            "criteria",
            "regex",
            "stop_processing",
            "tags",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class FolderSerializer(serializers.ModelSerializer):
    parent = OwnerScopedPKField(
        model=Folder, required=False, allow_null=True
    )
    tags = OwnerScopedPKField(model=Tag, many=True, required=False)
    transaction_count = serializers.SerializerMethodField()

    class Meta:
        model = Folder
        fields = [
            "id",
            "name",
            "parent",
            "tags",
            "tag_match",
            "criteria",
            "transaction_count",
            "created_at",
        ]
        read_only_fields = ["id", "transaction_count", "created_at"]

    def get_transaction_count(self, obj):
        from .folders import folder_transaction_ids

        return len(folder_transaction_ids(obj, recursive=True))


class FolderTransactionsSerializer(serializers.Serializer):
    add = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    remove = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)


class BulkTagSerializer(serializers.Serializer):
    transaction_ids = serializers.ListField(child=serializers.IntegerField())
    add = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    remove = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)


class AiClassifySerializer(serializers.Serializer):
    scope = serializers.CharField(required=False, default="untagged")
    transaction_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )
    limit = serializers.IntegerField(required=False, default=50, min_value=1, max_value=200)


class AiApplySerializer(serializers.Serializer):
    class _Item(serializers.Serializer):
        transaction_id = serializers.IntegerField()
        tag_ids = serializers.ListField(
            child=serializers.IntegerField(), required=False, default=list
        )
        new_tags = serializers.ListField(
            child=serializers.CharField(), required=False, default=list
        )
        confidence = serializers.FloatField(required=False, allow_null=True, default=None)

    items = _Item(many=True)


class ItemTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name", "color"]


class PurchaseItemSerializer(serializers.ModelSerializer):
    tags = ItemTagSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseItem
        fields = [
            "id",
            "name",
            "title",
            "barcode",
            "quantity",
            "unit_price",
            "amount",
            "category",
            "tags",
        ]


class ReceiptSerializer(serializers.ModelSerializer):
    items = PurchaseItemSerializer(many=True, read_only=True)
    file_url = serializers.SerializerMethodField()
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    details = serializers.SerializerMethodField()
    paid = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    class Meta:
        model = Receipt
        fields = [
            "id",
            "kind",
            "kind_label",
            "merchant",
            "amount",
            "currency",
            "document_date",
            "notes",
            "original_filename",
            "mime_type",
            "file_url",
            "details",
            "transaction",
            "items",
            "created_at",
            "paid",
            "status",
        ]
        read_only_fields = [
            "id",
            "kind",
            "kind_label",
            "original_filename",
            "mime_type",
            "file_url",
            "details",
            "transaction",
            "items",
            "created_at",
            "paid",
            "status",
        ]

    def get_file_url(self, obj):
        if not obj.file:
            return None
        request = self.context.get("request")
        path = f"/api/receipts/{obj.pk}/download/"
        return request.build_absolute_uri(path) if request else path

    def get_details(self, obj):
        skip = {"items", "merchant", "date", "amount", "currency", "kind", "notes"}
        out = {}
        for key, value in (obj.extracted or {}).items():
            if key in skip or value in (None, "", [], {}):
                continue
            if isinstance(value, (dict, list)):
                continue
            out[key] = value
        return out

    def get_paid(self, obj):
        tx = obj.transaction
        return bool(tx and tx.upload_id)

    def get_status(self, obj):
        if self.get_paid(obj):
            return "paid"
        if obj.document_date and obj.document_date < dt.date.today():
            return "overdue"
        return "unpaid"
