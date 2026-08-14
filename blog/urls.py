from django.urls import path

from .views import (
    BlogCategoryListAPIView,
    BlogPostDetailAPIView,
    BlogPostListAPIView,
    BlogPostViewAPIView,
)


app_name = 'blog'

urlpatterns = [
    path('posts/', BlogPostListAPIView.as_view(), name='post-list'),
    path(
        'posts/<slug:slug>/view/',
        BlogPostViewAPIView.as_view(),
        name='post-view',
    ),
    path(
        'posts/<slug:slug>/',
        BlogPostDetailAPIView.as_view(),
        name='post-detail',
    ),
    path(
        'categories/',
        BlogCategoryListAPIView.as_view(),
        name='category-list',
    ),
]


insurance_urlpatterns = [
    path(
        'posts/',
        BlogPostListAPIView.as_view(channel='insurance'),
        name='insurance-post-list',
    ),
    path(
        'posts/<slug:slug>/views/',
        BlogPostViewAPIView.as_view(channel='insurance'),
        name='insurance-post-view',
    ),
    path(
        'posts/<slug:slug>/',
        BlogPostDetailAPIView.as_view(channel='insurance'),
        name='insurance-post-detail',
    ),
    path(
        'categories/',
        BlogCategoryListAPIView.as_view(channel='insurance'),
        name='insurance-category-list',
    ),
]
