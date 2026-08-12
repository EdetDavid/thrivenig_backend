from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils.text import slugify
from rest_framework import serializers

from .models import BlogCategory, BlogPost, BlogTag


def normalize_label(value):
    return ' '.join(value.split())


def resolve_named_object(model, value):
    name = normalize_label(value)
    slug = slugify(name)
    if not slug:
        raise serializers.ValidationError('Enter a valid name.')

    lookup = Q(name__iexact=name) | Q(slug__iexact=slug)
    existing = model.objects.filter(lookup).order_by('id').first()
    if existing:
        return existing

    try:
        with transaction.atomic():
            return model.objects.create(name=name, slug=slug)
    except IntegrityError:
        existing = model.objects.filter(lookup).order_by('id').first()
        if existing:
            return existing
        raise


class TagNameListField(serializers.ListField):
    child = serializers.CharField(max_length=50, allow_blank=False)

    def to_representation(self, value):
        if hasattr(value, 'all'):
            value = value.all()
        return [item.name if isinstance(item, BlogTag) else str(item) for item in value]


class BlogPostQuerySerializer(serializers.Serializer):
    q = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=120,
    )
    category = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=90,
    )
    tag = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=60,
    )
    featured = serializers.BooleanField(required=False)


class BlogAdminPostQuerySerializer(BlogPostQuerySerializer):
    status = serializers.ChoiceField(
        choices=BlogPost.STATUS_CHOICES,
        required=False,
    )


class BlogPostViewSerializer(serializers.Serializer):
    visitor_id = serializers.RegexField(
        regex=r'^[A-Za-z0-9_-]{8,128}$',
        max_length=128,
        trim_whitespace=True,
        error_messages={
            'invalid': 'Enter a valid anonymous visitor identifier.',
        },
    )


class BlogAnalyticsQuerySerializer(serializers.Serializer):
    days = serializers.CharField(required=False, default='30', max_length=3)

    def validate_days(self, value):
        normalized = value.strip().lower()
        if normalized == 'all':
            return 'all'
        try:
            days = int(normalized)
        except (TypeError, ValueError) as exc:
            raise serializers.ValidationError(
                'Use all or a whole number from 1 to 365.'
            ) from exc
        if not 1 <= days <= 365:
            raise serializers.ValidationError(
                'Use all or a whole number from 1 to 365.'
            )
        return days


class BlogCategorySerializer(serializers.ModelSerializer):
    post_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = BlogCategory
        fields = ['name', 'slug', 'post_count']
        read_only_fields = fields


class BlogPostListSerializer(serializers.ModelSerializer):
    category = serializers.CharField(source='category.name', read_only=True)
    tags = TagNameListField(read_only=True)
    author_name = serializers.CharField(read_only=True)
    read_time_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = BlogPost
        fields = [
            'id',
            'slug',
            'title',
            'excerpt',
            'category',
            'tags',
            'cover_image_url',
            'cover_image_alt',
            'cover_image_caption',
            'author_name',
            'is_featured',
            'read_time_minutes',
            'published_at',
            'updated_at',
        ]
        read_only_fields = fields


class BlogPostDetailSerializer(BlogPostListSerializer):
    class Meta(BlogPostListSerializer.Meta):
        fields = BlogPostListSerializer.Meta.fields + [
            'content',
            'seo_title',
            'meta_description',
        ]


class BlogPostAdminSerializer(serializers.ModelSerializer):
    slug = serializers.CharField(required=False, max_length=220)
    category = serializers.CharField(max_length=80, allow_blank=False)
    tags = TagNameListField(required=False, allow_empty=True, max_length=12)
    author_name = serializers.CharField(read_only=True)
    read_time_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = BlogPost
        fields = [
            'id',
            'slug',
            'title',
            'excerpt',
            'content',
            'category',
            'tags',
            'cover_image_url',
            'cover_image_alt',
            'cover_image_caption',
            'author_name',
            'status',
            'is_featured',
            'read_time_minutes',
            'published_at',
            'seo_title',
            'meta_description',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'author_name',
            'read_time_minutes',
            'created_at',
            'updated_at',
        ]

    def validate_category(self, value):
        normalized = normalize_label(value)
        if not normalized:
            raise serializers.ValidationError('Category cannot be empty.')
        return normalized

    def validate_tags(self, value):
        normalized = []
        seen = set()
        for tag in value:
            item = normalize_label(tag)
            if not item:
                raise serializers.ValidationError('Tags cannot be empty.')
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(item)
        return normalized

    def validate(self, attrs):
        attrs = super().validate(attrs)

        for field_name in (
            'title',
            'excerpt',
            'cover_image_alt',
            'cover_image_caption',
            'seo_title',
            'meta_description',
        ):
            if field_name in attrs:
                attrs[field_name] = normalize_label(attrs[field_name])

        if 'content' in attrs:
            attrs['content'] = attrs['content'].strip()
            if not attrs['content']:
                raise serializers.ValidationError(
                    {'content': 'Article content cannot be empty.'}
                )

        supplied_slug = attrs.get('slug')
        if supplied_slug is None:
            if self.instance is None:
                supplied_slug = attrs.get('title', '')
            else:
                supplied_slug = self.instance.slug
        normalized_slug = slugify(supplied_slug)
        if not normalized_slug:
            raise serializers.ValidationError(
                {'slug': 'Enter a valid URL slug.'}
            )
        slug_query = BlogPost.objects.filter(slug__iexact=normalized_slug)
        if self.instance is not None:
            slug_query = slug_query.exclude(pk=self.instance.pk)
        if slug_query.exists():
            raise serializers.ValidationError(
                {'slug': 'A blog post with this slug already exists.'}
            )
        attrs['slug'] = normalized_slug

        current_status = (
            self.instance.status if self.instance else BlogPost.STATUS_DRAFT
        )
        current_published_at = (
            self.instance.published_at if self.instance else None
        )
        post_status = attrs.get('status', current_status)
        published_at = attrs.get('published_at', current_published_at)
        if post_status == BlogPost.STATUS_PUBLISHED and published_at is None:
            raise serializers.ValidationError(
                {
                    'published_at': (
                        'Published posts require a publication date. Future '
                        'dates are allowed for scheduled publication.'
                    )
                }
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        category_name = validated_data.pop('category')
        tag_names = validated_data.pop('tags', [])
        category = resolve_named_object(BlogCategory, category_name)
        tags = [resolve_named_object(BlogTag, name) for name in tag_names]
        post = BlogPost.objects.create(category=category, **validated_data)
        post.tags.set(tags)
        return post

    @transaction.atomic
    def update(self, instance, validated_data):
        category_name = validated_data.pop('category', None)
        tag_names = validated_data.pop('tags', None)
        if category_name is not None:
            validated_data['category'] = resolve_named_object(
                BlogCategory,
                category_name,
            )
        instance = super().update(instance, validated_data)
        if tag_names is not None:
            tags = [
                resolve_named_object(BlogTag, name)
                for name in tag_names
            ]
            instance.tags.set(tags)
        return instance
