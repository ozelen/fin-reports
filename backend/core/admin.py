from django.contrib import admin

from .models import (
    Account,
    Budget,
    Client,
    Document,
    Folder,
    FxRate,
    Invoice,
    IssuerProfile,
    PurchaseItem,
    Receipt,
    Recurrence,
    Rule,
    Tag,
    TaxProfile,
    TelegramLink,
    Transaction,
    TransactionTag,
    Upload,
)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "kind",
        "bank",
        "group",
        "currency",
        "balance",
        "credit_limit",
        "is_default",
        "is_invoice_default",
        "owner",
        "created_at",
    )
    list_filter = (
        "owner",
        "kind",
        "group",
        "currency",
        "is_default",
        "is_invoice_default",
    )
    search_fields = ("name", "bank", "iban", "bic")


@admin.register(Upload)
class UploadAdmin(admin.ModelAdmin):
    list_display = (
        "original_filename",
        "account",
        "owner",
        "row_count",
        "imported_count",
        "created_at",
    )
    list_filter = ("owner", "account", "currency")
    search_fields = ("original_filename", "account_iban", "account_holder")


class TransactionTagInline(admin.TabularInline):
    model = TransactionTag
    extra = 0
    autocomplete_fields = ("tag", "rule")


class TxPurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    fk_name = "transaction"
    extra = 0
    fields = (
        "title",
        "name",
        "barcode",
        "quantity",
        "amount",
        "category",
        "telegram_photo_file_id",
        "receipt",
    )
    readonly_fields = ("receipt",)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "operation_date",
        "amount",
        "currency",
        "account",
        "counterparty",
        "concept",
        "pending",
        "owner",
    )
    list_filter = ("owner", "account", "currency", "operation_date")
    search_fields = ("concept", "counterparty")
    inlines = [TransactionTagInline, TxPurchaseItemInline]

    @admin.display(boolean=True)
    def pending(self, obj):
        return obj.upload_id is None


@admin.register(FxRate)
class FxRateAdmin(admin.ModelAdmin):
    list_display = ("date", "currency", "uah_per_unit")
    list_filter = ("currency",)
    date_hierarchy = "date"


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "color", "owner", "created_at")
    list_filter = ("owner",)
    search_fields = ("name",)


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = (
        "tag",
        "kind",
        "period",
        "amount",
        "account",
        "is_active",
        "owner",
        "created_at",
    )
    list_filter = ("owner", "kind", "period", "is_active")
    search_fields = ("tag__name",)


@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ("name", "order", "is_active", "owner", "created_at")
    list_filter = ("owner", "is_active")
    search_fields = ("name",)
    filter_horizontal = ("tags",)


@admin.register(Recurrence)
class RecurrenceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "amount",
        "frequency",
        "due_day",
        "auto_match",
        "is_active",
        "owner",
    )
    list_filter = ("owner", "category", "frequency", "is_active", "auto_match")
    search_fields = ("name", "match_text")
    filter_horizontal = ("tags",)


@admin.register(TaxProfile)
class TaxProfileAdmin(admin.ModelAdmin):
    list_display = (
        "owner",
        "irpf_method",
        "income_from",
        "hourly_rate",
        "ss_mode",
        "simplificada",
        "updated_at",
    )
    list_filter = ("irpf_method", "income_from", "ss_mode")
    filter_horizontal = ("deductible_tags",)


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "owner", "created_at")
    list_filter = ("owner",)
    search_fields = ("name",)
    filter_horizontal = ("included_transactions", "excluded_transactions", "tags")


@admin.register(IssuerProfile)
class IssuerProfileAdmin(admin.ModelAdmin):
    list_display = ("legal_name", "vat_number", "email", "owner", "updated_at")
    search_fields = ("legal_name", "vat_number", "email")


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "tax_id", "vat_mode", "currency", "owner", "created_at")
    list_filter = ("owner", "vat_mode", "currency")
    search_fields = ("name", "tax_id")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "kind",
        "client",
        "document_date",
        "owner",
        "created_at",
    )
    list_filter = ("owner", "kind")
    search_fields = ("title", "original_filename", "notes")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "status",
        "client_name",
        "issue_date",
        "sale_date",
        "total_amount",
        "currency",
        "owner",
    )
    list_filter = ("owner", "status", "service_year", "currency")
    search_fields = ("number", "client_name", "description", "iban")
    readonly_fields = (
        "status",
        "net_amount",
        "vat_amount",
        "total_amount",
        "issued_at",
        "xlsx_file",
        "pdf_file",
        "issuer_name",
        "issuer_vat_number",
        "client_name",
        "iban",
        "bic",
    )


class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    fk_name = "receipt"
    extra = 0
    fields = (
        "name",
        "title",
        "barcode",
        "quantity",
        "unit_price",
        "amount",
        "category",
        "telegram_photo_file_id",
        "transaction",
    )


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "kind",
        "merchant",
        "amount",
        "currency",
        "document_date",
        "transaction",
        "source",
        "owner",
        "created_at",
    )
    list_filter = ("owner", "kind", "source", "currency")
    search_fields = ("merchant", "original_filename", "notes", "telegram_file_id")
    autocomplete_fields = ("transaction",)
    readonly_fields = ("telegram_file_id",)
    inlines = [PurchaseItemInline]


@admin.register(PurchaseItem)
class PurchaseItemAdmin(admin.ModelAdmin):
    list_display = (
        "label",
        "name",
        "barcode",
        "category",
        "quantity",
        "amount",
        "receipt",
        "transaction",
        "created_at",
    )
    list_filter = ("category",)
    search_fields = ("name", "title", "barcode", "category", "receipt__merchant")
    autocomplete_fields = ("receipt", "transaction")
    filter_horizontal = ("tags",)


@admin.register(TelegramLink)
class TelegramLinkAdmin(admin.ModelAdmin):
    list_display = (
        "telegram_user_id",
        "chat_id",
        "pending_item_id",
        "pending_upload_id",
        "owner",
        "updated_at",
    )
    list_filter = ("owner",)
