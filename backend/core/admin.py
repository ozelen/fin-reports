from django.contrib import admin

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


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "bank",
        "currency",
        "is_default",
        "is_invoice_default",
        "owner",
        "created_at",
    )
    list_filter = ("owner", "currency", "is_default", "is_invoice_default")
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


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "operation_date",
        "amount",
        "currency",
        "account",
        "counterparty",
        "concept",
        "owner",
    )
    list_filter = ("owner", "account", "currency", "operation_date")
    search_fields = ("concept", "counterparty")
    inlines = [TransactionTagInline]


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "color", "owner", "created_at")
    list_filter = ("owner",)
    search_fields = ("name",)


@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ("name", "order", "is_active", "owner", "created_at")
    list_filter = ("owner", "is_active")
    search_fields = ("name",)
    filter_horizontal = ("tags",)


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
