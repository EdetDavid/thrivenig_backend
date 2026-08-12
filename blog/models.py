import math
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.text import slugify
from django.utils import timezone

from .validators import validate_markdown_content


def normalize_slug(value, field_name='slug'):
    normalized = slugify(value or '')
    if not normalized:
        raise ValidationError({field_name: 'Enter a valid URL slug.'})
    return normalized


class BlogCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=90, unique=True)
    description = models.CharField(max_length=180, blank=True)

    class Meta:
        ordering = ('name',)
        verbose_name_plural = 'blog categories'
        constraints = [
            models.UniqueConstraint(
                Lower('slug'),
                name='blog_category_slug_ci_uniq',
            ),
        ]

    def save(self, *args, **kwargs):
        self.slug = normalize_slug(self.slug or self.name)
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class BlogTag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=60, unique=True)

    class Meta:
        ordering = ('name',)
        constraints = [
            models.UniqueConstraint(
                Lower('slug'),
                name='blog_tag_slug_ci_uniq',
            ),
        ]

    def save(self, *args, **kwargs):
        self.slug = normalize_slug(self.slug or self.name)
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class BlogPost(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUS_ARCHIVED = 'archived'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_PUBLISHED, 'Published'),
        (STATUS_ARCHIVED, 'Archived'),
    ]

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='blog_posts',
        blank=True,
        null=True,
    )
    category = models.ForeignKey(
        BlogCategory,
        on_delete=models.PROTECT,
        related_name='posts',
    )
    tags = models.ManyToManyField(
        BlogTag,
        related_name='posts',
        blank=True,
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    excerpt = models.CharField(max_length=360)
    content = models.TextField(
        validators=[
            MaxLengthValidator(100_000),
            validate_markdown_content,
        ],
        help_text='Markdown only. Raw HTML is not accepted.',
    )
    cover_image_url = models.URLField(max_length=1000)
    cover_image_alt = models.CharField(max_length=180)
    cover_image_caption = models.CharField(max_length=240, blank=True)
    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        db_index=True,
    )
    is_featured = models.BooleanField(default=False, db_index=True)
    published_at = models.DateTimeField(blank=True, null=True, db_index=True)
    seo_title = models.CharField(max_length=70, blank=True)
    meta_description = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-published_at', '-created_at', '-id')
        indexes = [
            models.Index(
                fields=('status', '-published_at'),
                name='blog_post_status_pub',
            ),
            models.Index(
                fields=('category', '-published_at'),
                name='blog_post_cat_pub',
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                Lower('slug'),
                name='blog_post_slug_ci_uniq',
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(status='published')
                    | Q(published_at__isnull=False)
                ),
                name='blog_post_published_at_req',
            ),
        ]

    def clean(self):
        super().clean()
        self.slug = normalize_slug(self.slug or self.title)
        if self.status == self.STATUS_PUBLISHED and self.published_at is None:
            raise ValidationError(
                {'published_at': 'Published posts require a publication date.'}
            )

    def save(self, *args, **kwargs):
        self.slug = normalize_slug(self.slug or self.title)
        return super().save(*args, **kwargs)

    @property
    def author_name(self):
        if self.author_id and self.author:
            return self.author.get_full_name().strip() or self.author.username
        return 'Thrive Travels Editorial Team'

    @property
    def read_time_minutes(self):
        word_count = len(re.findall(r"\b[\w'-]+\b", self.content or ''))
        return max(1, math.ceil(word_count / 200))

    def __str__(self):
        return self.title


class BlogPostView(models.Model):
    """Privacy-preserving, durable view event for one public article."""

    post = models.ForeignKey(
        BlogPost,
        on_delete=models.CASCADE,
        related_name='views',
    )
    visitor_hash = models.CharField(max_length=64, db_index=True)
    viewed_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ('-viewed_at', '-id')
        indexes = [
            models.Index(
                fields=('post', '-viewed_at'),
                name='blog_view_post_viewed',
            ),
            models.Index(
                fields=('post', 'visitor_hash', '-viewed_at'),
                name='blog_view_post_visitor',
            ),
        ]

    def __str__(self):
        return f'View of {self.post_id} at {self.viewed_at.isoformat()}'
