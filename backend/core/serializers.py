from rest_framework import serializers

from .models import (
    Account,
    Client,
    Folder,
    Invoice,
    IssuerProfile,
    Rule,
    Tag,
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

    class Meta:
        model = Account
        fields = [
            "id",
            "name",
            "bank",
            "iban",
            "bic",
            "correspondent_bic",
            "bank_address",
            "currency",
            "is_default",
            "is_invoice_default",
            "transaction_count",
            "created_at",
        ]
        read_only_fields = ["id", "transaction_count", "created_at"]


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
        fields = ["id", "name", "color", "description", "transaction_count", "created_at"]
        read_only_fields = ["id", "transaction_count", "created_at"]


class TransactionTagSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="tag.id", read_only=True)
    name = serializers.CharField(source="tag.name", read_only=True)
    color = serializers.CharField(source="tag.color", read_only=True)

    class Meta:
        model = TransactionTag
        fields = ["id", "name", "color", "source", "confidence"]


class TransactionSerializer(serializers.ModelSerializer):
    kind = serializers.CharField(read_only=True)
    tags = TransactionTagSerializer(source="tag_links", many=True, read_only=True)
    account_label = serializers.CharField(source="account.name", read_only=True)

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
            "tags",
            "metadata",
            "upload",
            "account",
            "account_label",
            "created_at",
        ]
        read_only_fields = fields


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
