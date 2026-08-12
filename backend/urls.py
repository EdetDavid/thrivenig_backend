from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.conf import settings
from base.views import LoginAPIView

urlpatterns = [
    path('admin/', admin.site.urls),
    path("api/blog/", include('blog.urls')),
    path("api/travel-admin/blog/", include('blog.admin_urls')),
    path("api/", include('base.urls')),
    path("api/auth/", LoginAPIView.as_view()),
]


# Retrieve images from /media/
urlpatterns += staticfiles_urlpatterns()
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
