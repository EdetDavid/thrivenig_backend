from django.contrib import admin

from .models import BlogCategory, BlogImage, BlogPost, BlogPostView, BlogTag


@admin.register(BlogCategory)
class BlogCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(BlogTag)
class BlogTagAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'channel',
        'category',
        'status',
        'is_featured',
        'author',
        'published_at',
        'updated_at',
    )
    list_filter = (
        'channel',
        'status',
        'is_featured',
        'category',
        'published_at',
    )
    search_fields = ('title', 'excerpt', 'content', 'author__username')
    prepopulated_fields = {'slug': ('title',)}
    filter_horizontal = ('tags',)
    autocomplete_fields = ('author', 'category')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'published_at'
    list_select_related = ('author', 'category')

    def get_readonly_fields(self, request, obj=None):
        if obj is not None:
            return (*self.readonly_fields, 'channel')
        return self.readonly_fields

    def save_model(self, request, obj, form, change):
        if obj.author_id is None:
            obj.author = request.user
        super().save_model(request, obj, form, change)


@admin.register(BlogPostView)
class BlogPostViewAdmin(admin.ModelAdmin):
    list_display = ('post', 'viewed_at')
    list_filter = ('viewed_at',)
    search_fields = ('post__title', 'post__slug')
    readonly_fields = ('post', 'visitor_hash', 'viewed_at')
    date_hierarchy = 'viewed_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(BlogImage)
class BlogImageAdmin(admin.ModelAdmin):
    list_display = (
        'image',
        'channel',
        'uploaded_by',
        'content_type',
        'width',
        'height',
        'size_bytes',
        'created_at',
    )
    list_filter = ('channel', 'content_type', 'created_at')
    search_fields = ('image', 'uploaded_by__username')
    readonly_fields = (
        'image',
        'channel',
        'uploaded_by',
        'width',
        'height',
        'content_type',
        'size_bytes',
        'created_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
