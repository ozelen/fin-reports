from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("core.urls")),
    # ponytail: gunicorn does not serve STATIC_ROOT/MEDIA_ROOT when DEBUG=0
    re_path(rf"^{settings.STATIC_URL.lstrip('/')}(?P<path>.*)$", serve, {"document_root": settings.STATIC_ROOT}),
    re_path(rf"^{settings.MEDIA_URL.lstrip('/')}(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
