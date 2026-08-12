import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Max, Q
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveAPIView,
    RetrieveUpdateDestroyAPIView,
)
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView

from base.permissions import CanManageContent

from .models import BlogCategory, BlogPost, BlogPostView
from .serializers import (
    BlogAnalyticsQuerySerializer,
    BlogAdminPostQuerySerializer,
    BlogCategorySerializer,
    BlogPostAdminSerializer,
    BlogPostDetailSerializer,
    BlogPostListSerializer,
    BlogPostQuerySerializer,
    BlogPostViewSerializer,
)


def blog_post_queryset():
    return BlogPost.objects.select_related(
        'author',
        'category',
    ).prefetch_related('tags')


def public_blog_post_queryset():
    return blog_post_queryset().filter(
        status=BlogPost.STATUS_PUBLISHED,
        published_at__isnull=False,
        published_at__lte=timezone.now(),
    )


def filter_blog_posts(queryset, filters):
    query = filters.get('q', '').strip()
    if query:
        queryset = queryset.filter(
            Q(title__icontains=query)
            | Q(excerpt__icontains=query)
            | Q(content__icontains=query)
        )

    category = filters.get('category', '').strip()
    if category:
        queryset = queryset.filter(
            Q(category__name__iexact=category)
            | Q(category__slug__iexact=category)
        )

    tag = filters.get('tag', '').strip()
    if tag:
        queryset = queryset.filter(
            Q(tags__name__iexact=tag)
            | Q(tags__slug__iexact=tag)
        )

    if 'featured' in filters:
        queryset = queryset.filter(is_featured=filters['featured'])
    return queryset.distinct()


class BlogPagination(PageNumberPagination):
    page_size = 9
    page_size_query_param = 'page_size'
    max_page_size = 24


class BlogAdminPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100


class BlogPostListAPIView(ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = BlogPostListSerializer
    pagination_class = BlogPagination

    def get_queryset(self):
        query_serializer = BlogPostQuerySerializer(
            data=self.request.query_params.dict()
        )
        query_serializer.is_valid(raise_exception=True)
        return filter_blog_posts(
            public_blog_post_queryset(),
            query_serializer.validated_data,
        )


class BlogPostDetailAPIView(RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = BlogPostDetailSerializer
    lookup_field = 'slug'

    def get_queryset(self):
        return public_blog_post_queryset()


def hash_visitor_identifier(visitor_id):
    """Create a stable keyed digest without retaining the browser identifier."""
    return hmac.new(
        settings.SECRET_KEY.encode('utf-8'),
        f'thrive-blog-view:v1:{visitor_id}'.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


class BlogPostViewAPIView(APIView):
    permission_classes = [AllowAny]
    deduplication_window = timedelta(minutes=30)

    def post(self, request, slug):
        serializer = BlogPostViewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        visitor_hash = hash_visitor_identifier(
            serializer.validated_data['visitor_id']
        )
        now = timezone.now()

        # Locking one post makes the rolling deduplication check deterministic
        # even when a browser retries two requests at the same time.
        with transaction.atomic():
            post = get_object_or_404(
                BlogPost.objects.select_for_update().filter(
                    status=BlogPost.STATUS_PUBLISHED,
                    published_at__isnull=False,
                    published_at__lte=now,
                ),
                slug=slug,
            )
            already_recorded = BlogPostView.objects.filter(
                post=post,
                visitor_hash=visitor_hash,
                viewed_at__gte=now - self.deduplication_window,
            ).exists()
            if not already_recorded:
                BlogPostView.objects.create(
                    post=post,
                    visitor_hash=visitor_hash,
                    viewed_at=now,
                )

        return Response(
            {'recorded': not already_recorded},
            status=(
                status.HTTP_200_OK
                if already_recorded
                else status.HTTP_201_CREATED
            ),
        )


class BlogCategoryListAPIView(ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = BlogCategorySerializer
    pagination_class = None

    def get_queryset(self):
        now = timezone.now()
        return BlogCategory.objects.annotate(
            post_count=Count(
                'posts',
                filter=Q(
                    posts__status=BlogPost.STATUS_PUBLISHED,
                    posts__published_at__isnull=False,
                    posts__published_at__lte=now,
                ),
                distinct=True,
            )
        ).filter(post_count__gt=0).order_by('name')


class BlogAdminPostListAPIView(ListCreateAPIView):
    permission_classes = [CanManageContent]
    serializer_class = BlogPostAdminSerializer
    pagination_class = BlogAdminPagination

    def get_queryset(self):
        query_serializer = BlogAdminPostQuerySerializer(
            data=self.request.query_params.dict()
        )
        query_serializer.is_valid(raise_exception=True)
        queryset = blog_post_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(author=self.request.user)
        queryset = filter_blog_posts(
            queryset,
            query_serializer.validated_data,
        )
        post_status = query_serializer.validated_data.get('status')
        if post_status:
            queryset = queryset.filter(status=post_status)
        return queryset.order_by('-updated_at', '-id')

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


class BlogAdminPostDetailAPIView(RetrieveUpdateDestroyAPIView):
    permission_classes = [CanManageContent]
    serializer_class = BlogPostAdminSerializer

    def get_queryset(self):
        queryset = blog_post_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(author=self.request.user)
        return queryset

    def perform_update(self, serializer):
        if serializer.instance.author_id is None:
            serializer.save(author=self.request.user)
        else:
            serializer.save()


class BlogAnalyticsAPIView(APIView):
    permission_classes = [CanManageContent]

    def get(self, request):
        query_serializer = BlogAnalyticsQuerySerializer(
            data=request.query_params
        )
        query_serializer.is_valid(raise_exception=True)
        period_days = query_serializer.validated_data['days']
        now = timezone.now()
        cutoff = (
            None
            if period_days == 'all'
            else timezone.make_aware(
                timezone.datetime.combine(
                    timezone.localdate(now) - timedelta(
                        days=period_days - 1
                    ),
                    timezone.datetime.min.time(),
                ),
                timezone.get_current_timezone(),
            )
        )

        scoped_posts = blog_post_queryset()
        scope = 'all'
        if not request.user.is_staff:
            scope = 'author'
            scoped_posts = scoped_posts.filter(author=request.user)

        summary = scoped_posts.aggregate(
            posts=Count('id'),
            published=Count(
                'id',
                filter=Q(status=BlogPost.STATUS_PUBLISHED),
            ),
            drafts=Count(
                'id',
                filter=Q(status=BlogPost.STATUS_DRAFT),
            ),
            archived=Count(
                'id',
                filter=Q(status=BlogPost.STATUS_ARCHIVED),
            ),
        )
        scoped_views = BlogPostView.objects.filter(
            post__in=scoped_posts.order_by().values('pk')
        )
        all_view_totals = scoped_views.aggregate(
            total_views=Count('id'),
            unique_viewers=Count('visitor_hash', distinct=True),
        )
        period_views = scoped_views
        if cutoff is not None:
            period_views = period_views.filter(
                viewed_at__gte=cutoff,
                viewed_at__lte=now,
            )
        period_view_totals = period_views.aggregate(
            period_views=Count('id'),
            period_unique_viewers=Count('visitor_hash', distinct=True),
        )
        summary.update(all_view_totals)
        summary.update(period_view_totals)

        view_annotations = {
            'total_views': Count('views'),
            'unique_viewers': Count('views__visitor_hash', distinct=True),
            'last_viewed_at': Max('views__viewed_at'),
        }
        if cutoff is None:
            view_annotations.update(
                period_views=Count('views'),
                period_unique_viewers=Count(
                    'views__visitor_hash',
                    distinct=True,
                ),
            )
        else:
            period_filter = Q(
                views__viewed_at__gte=cutoff,
                views__viewed_at__lte=now,
            )
            view_annotations.update(
                period_views=Count('views', filter=period_filter),
                period_unique_viewers=Count(
                    'views__visitor_hash',
                    filter=period_filter,
                    distinct=True,
                ),
            )

        post_rows = []
        for post in scoped_posts.annotate(**view_annotations).order_by(
            '-period_views',
            '-total_views',
            '-updated_at',
            '-id',
        )[:100]:
            post_rows.append(
                {
                    'id': post.id,
                    'title': post.title,
                    'slug': post.slug,
                    'status': post.status,
                    'published_at': post.published_at,
                    'total_views': post.total_views,
                    'unique_viewers': post.unique_viewers,
                    'period_views': post.period_views,
                    'period_unique_viewers': post.period_unique_viewers,
                    'last_viewed_at': post.last_viewed_at,
                }
            )

        daily_totals = {
            row['date']: {
                'views': row['views'],
                'unique_viewers': row['unique_viewers'],
            }
            for row in period_views.annotate(
                date=TruncDate('viewed_at')
            ).values('date').annotate(
                views=Count('id'),
                unique_viewers=Count('visitor_hash', distinct=True),
            ).order_by('date')
        }
        if period_days == 'all':
            first_date = min(daily_totals, default=None)
        else:
            first_date = timezone.localdate(now) - timedelta(
                days=period_days - 1
            )
        last_date = timezone.localdate(now)
        daily_views = []
        current_date = first_date
        while current_date is not None and current_date <= last_date:
            totals = daily_totals.get(
                current_date,
                {'views': 0, 'unique_viewers': 0},
            )
            daily_views.append(
                {
                    'date': current_date,
                    **totals,
                }
            )
            current_date += timedelta(days=1)

        return Response(
            {
                'period_days': period_days,
                'scope': scope,
                'summary': summary,
                'posts': post_rows,
                'daily_views': daily_views,
            }
        )
