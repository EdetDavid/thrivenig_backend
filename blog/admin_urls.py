from django.urls import path

from .views import (
    BlogAnalyticsAPIView,
    BlogImageUploadAPIView,
    BlogAdminPostDetailAPIView,
    BlogAdminPostListAPIView,
)


app_name = 'blog-admin'

urlpatterns = [
    path('analytics/', BlogAnalyticsAPIView.as_view(), name='analytics'),
    path(
        'media/images/',
        BlogImageUploadAPIView.as_view(),
        name='image-upload',
    ),
    path('posts/', BlogAdminPostListAPIView.as_view(), name='post-list'),
    path(
        'posts/<int:pk>/',
        BlogAdminPostDetailAPIView.as_view(),
        name='post-detail',
    ),
]


insurance_urlpatterns = [
    path(
        'analytics/',
        BlogAnalyticsAPIView.as_view(channel='insurance'),
        name='insurance-analytics',
    ),
    path(
        'media/images/',
        BlogImageUploadAPIView.as_view(channel='insurance'),
        name='insurance-image-upload',
    ),
    path(
        'posts/',
        BlogAdminPostListAPIView.as_view(channel='insurance'),
        name='insurance-post-list',
    ),
    path(
        'posts/<int:pk>/',
        BlogAdminPostDetailAPIView.as_view(channel='insurance'),
        name='insurance-post-detail',
    ),
]
