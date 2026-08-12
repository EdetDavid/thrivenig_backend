from django.urls import path

from .views import (
    BlogAnalyticsAPIView,
    BlogAdminPostDetailAPIView,
    BlogAdminPostListAPIView,
)


app_name = 'blog-admin'

urlpatterns = [
    path('analytics/', BlogAnalyticsAPIView.as_view(), name='analytics'),
    path('posts/', BlogAdminPostListAPIView.as_view(), name='post-list'),
    path(
        'posts/<int:pk>/',
        BlogAdminPostDetailAPIView.as_view(),
        name='post-detail',
    ),
]
