from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.http import FileResponse, Http404
from django.urls import include, path, re_path
from django.views.static import serve


def spa(request, path=""):
    root = Path(settings.FRONTEND_DIR).resolve()
    if not root.is_dir():
        raise Http404()
    rel = path.strip("/")
    if rel:
        candidate = (root / rel).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise Http404() from exc
        if candidate.is_file():
            return serve(request, rel, document_root=root)
    index = root / "index.html"
    if not index.is_file():
        raise Http404()
    resp = FileResponse(index.open("rb"), content_type="text/html")
    resp["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("core.urls")),
    # ponytail: gunicorn does not serve STATIC_ROOT/MEDIA_ROOT when DEBUG=0
    re_path(rf"^{settings.STATIC_URL.lstrip('/')}(?P<path>.*)$", serve, {"document_root": settings.STATIC_ROOT}),
    re_path(rf"^{settings.MEDIA_URL.lstrip('/')}(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    re_path(r"^(?P<path>.*)$", spa),
]
