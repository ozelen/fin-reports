from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    AccountViewSet,
    AiViewSet,
    BackupExportView,
    BackupImportView,
    ClientViewSet,
    FolderViewSet,
    InvoiceViewSet,
    IssuerProfileView,
    RuleViewSet,
    TagViewSet,
    TransactionViewSet,
    UploadViewSet,
)

router = DefaultRouter()
router.register("uploads", UploadViewSet, basename="upload")
router.register("transactions", TransactionViewSet, basename="transaction")
router.register("accounts", AccountViewSet, basename="account")
router.register("folders", FolderViewSet, basename="folder")
router.register("tags", TagViewSet, basename="tag")
router.register("rules", RuleViewSet, basename="rule")
router.register("ai", AiViewSet, basename="ai")
router.register("clients", ClientViewSet, basename="client")
router.register("invoices", InvoiceViewSet, basename="invoice")

urlpatterns = [
    path("auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("backup/export/", BackupExportView.as_view(), name="backup_export"),
    path("backup/import/", BackupImportView.as_view(), name="backup_import"),
    path("issuer/", IssuerProfileView.as_view(), name="issuer_profile"),
    path("", include(router.urls)),
]
