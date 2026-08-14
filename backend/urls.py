from django.contrib import admin
from django.http import Http404
from django.urls import path, include, re_path
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.conf import settings
from django.views.static import serve as serve_static_file
from base.views import LoginAPIView
from blog.admin_urls import insurance_urlpatterns as insurance_admin_urls
from blog.urls import insurance_urlpatterns as insurance_blog_urls


def serve_local_media(request, path):
    """Serve uploaded files only when explicitly enabled for local use."""
    if not settings.SERVE_MEDIA_FILES or settings.USE_B2_STORAGE:
        raise Http404
    return serve_static_file(
        request,
        path,
        document_root=settings.MEDIA_ROOT,
    )

urlpatterns = [
    path('admin/', admin.site.urls),
    path("api/blog/", include('blog.urls')),
    path("api/insurance/blog/", include(insurance_blog_urls)),
    path("api/travel-admin/blog/", include('blog.admin_urls')),
    path(
        "api/travel-admin/insurance-blog/",
        include(insurance_admin_urls),
    ),
    path("api/", include('base.urls')),
    path("api/auth/", LoginAPIView.as_view()),
    re_path(r'^media/(?P<path>.*)$', serve_local_media),
]


# Retrieve images from /media/
urlpatterns += staticfiles_urlpatterns()
