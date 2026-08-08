from django.contrib import admin

from .models import Account, Folder, Rule, Tag, Transaction, TransactionTag, Upload


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("name", "bank", "currency", "is_default", "owner", "created_at")
    list_filter = ("owner", "currency", "is_default")
    search_fields = ("name", "bank", "iban")


@admin.register(Upload)
class UploadAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "account", "owner", "row_count", "imported_count", "created_at")
    list_filter = ("owner", "account", "currency")
    search_fields = ("original_filename", "account_iban", "account_holder")


class TransactionTagInline(admin.TabularInline):
    model = TransactionTag
    extra = 0
    autocomplete_fields = ("tag", "rule")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("operation_date", "amount", "currency", "account", "counterparty", "concept", "owner")
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
