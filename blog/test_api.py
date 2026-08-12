from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import BlogCategory, BlogPost, BlogTag


class BlogPublicAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.now = timezone.now()
        cls.author = User.objects.create(
            username='editor',
            first_name='Toyin',
            last_name='Adewuyi',
        )
        cls.category = BlogCategory.objects.create(
            name='Travel Guides',
            slug='travel-guides',
        )
        cls.hidden_category = BlogCategory.objects.create(
            name='Internal News',
            slug='internal-news',
        )
        cls.tag = BlogTag.objects.create(name='Visa Tips', slug='visa-tips')
        cls.featured = BlogPost.objects.create(
            author=cls.author,
            category=cls.category,
            title='A practical Lagos travel guide',
            slug='lagos-travel-guide',
            excerpt='Everything a thoughtful traveler needs before departure.',
            content=' '.join(['journey'] * 401),
            cover_image_url='https://images.example.com/lagos.jpg',
            cover_image_alt='Lagos skyline at sunset',
            cover_image_caption='Lagos, Nigeria',
            status=BlogPost.STATUS_PUBLISHED,
            is_featured=True,
            published_at=cls.now - timedelta(days=1),
            seo_title='A practical guide to Lagos',
            meta_description='Plan a smooth and memorable visit to Lagos.',
        )
        cls.featured.tags.add(cls.tag)
        cls.older = BlogPost.objects.create(
            author=cls.author,
            category=cls.category,
            title='How to pack with confidence',
            slug='pack-with-confidence',
            excerpt='A compact checklist for calmer travel days.',
            content='Use a checklist and pack versatile layers.',
            cover_image_url='https://images.example.com/luggage.jpg',
            cover_image_alt='A neatly packed suitcase',
            status=BlogPost.STATUS_PUBLISHED,
            published_at=cls.now - timedelta(days=4),
        )
        cls.draft = BlogPost.objects.create(
            author=cls.author,
            category=cls.hidden_category,
            title='Draft article',
            slug='draft-article',
            excerpt='This copy is not ready for readers.',
            content='Draft Markdown content.',
            cover_image_url='https://images.example.com/draft.jpg',
            cover_image_alt='Draft cover',
            status=BlogPost.STATUS_DRAFT,
        )
        cls.archived = BlogPost.objects.create(
            author=cls.author,
            category=cls.category,
            title='Archived article',
            slug='archived-article',
            excerpt='This article has been retired.',
            content='Archived Markdown content.',
            cover_image_url='https://images.example.com/archive.jpg',
            cover_image_alt='Archived cover',
            status=BlogPost.STATUS_ARCHIVED,
            published_at=cls.now - timedelta(days=10),
        )
        cls.scheduled = BlogPost.objects.create(
            author=cls.author,
            category=cls.category,
            title='Scheduled article',
            slug='scheduled-article',
            excerpt='This article will be available later.',
            content='Scheduled Markdown content.',
            cover_image_url='https://images.example.com/scheduled.jpg',
            cover_image_alt='Scheduled cover',
            status=BlogPost.STATUS_PUBLISHED,
            published_at=cls.now + timedelta(days=2),
        )

    def test_public_list_has_contract_and_hides_non_public_posts(self):
        response = APIClient().get('/api/blog/posts/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            set(response.data),
            {'count', 'next', 'previous', 'results'},
        )
        self.assertEqual(response.data['count'], 2)
        rows = response.data['results']
        self.assertEqual(
            [row['slug'] for row in rows],
            ['lagos-travel-guide', 'pack-with-confidence'],
        )
        self.assertEqual(
            set(rows[0]),
            {
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
            },
        )
        self.assertEqual(rows[0]['category'], 'Travel Guides')
        self.assertEqual(rows[0]['tags'], ['Visa Tips'])
        self.assertEqual(rows[0]['author_name'], 'Toyin Adewuyi')
        self.assertEqual(rows[0]['read_time_minutes'], 3)
        self.assertNotIn('content', rows[0])

    def test_public_detail_has_content_and_seo_but_never_leaks_hidden_posts(self):
        response = APIClient().get(
            f'/api/blog/posts/{self.featured.slug}/'
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['content'], self.featured.content)
        self.assertEqual(
            response.data['seo_title'],
            'A practical guide to Lagos',
        )
        self.assertEqual(
            response.data['meta_description'],
            'Plan a smooth and memorable visit to Lagos.',
        )
        for post in (self.draft, self.archived, self.scheduled):
            hidden = APIClient().get(f'/api/blog/posts/{post.slug}/')
            self.assertEqual(hidden.status_code, 404, post.slug)

    def test_public_filters_accept_category_and_tag_names_or_slugs(self):
        client = APIClient()
        cases = [
            ({'q': 'Lagos'}, ['lagos-travel-guide']),
            ({'category': 'Travel Guides'}, [
                'lagos-travel-guide',
                'pack-with-confidence',
            ]),
            ({'category': 'travel-guides'}, [
                'lagos-travel-guide',
                'pack-with-confidence',
            ]),
            ({'tag': 'Visa Tips'}, ['lagos-travel-guide']),
            ({'tag': 'visa-tips'}, ['lagos-travel-guide']),
            ({'featured': 'true'}, ['lagos-travel-guide']),
            ({'featured': 'false'}, ['pack-with-confidence']),
        ]
        for params, expected_slugs in cases:
            with self.subTest(params=params):
                response = client.get('/api/blog/posts/', params)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(
                    [row['slug'] for row in response.data['results']],
                    expected_slugs,
                )

    def test_public_pagination_defaults_to_nine_and_caps_page_size_at_24(self):
        BlogPost.objects.bulk_create(
            [
                BlogPost(
                    author=self.author,
                    category=self.category,
                    title=f'Additional guide {number}',
                    slug=f'additional-guide-{number}',
                    excerpt='Another useful travel guide.',
                    content='Practical travel information.',
                    cover_image_url=(
                        f'https://images.example.com/guide-{number}.jpg'
                    ),
                    cover_image_alt=f'Travel guide {number}',
                    status=BlogPost.STATUS_PUBLISHED,
                    published_at=self.now - timedelta(hours=number + 2),
                )
                for number in range(25)
            ]
        )

        default_page = APIClient().get('/api/blog/posts/')
        capped_page = APIClient().get(
            '/api/blog/posts/',
            {'page_size': 100},
        )

        self.assertEqual(len(default_page.data['results']), 9)
        self.assertEqual(default_page.data['count'], 27)
        self.assertEqual(len(capped_page.data['results']), 24)
        self.assertEqual(capped_page.data['count'], 27)

    def test_categories_include_only_categories_with_live_posts(self):
        response = APIClient().get('/api/blog/categories/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data,
            [
                {
                    'name': 'Travel Guides',
                    'slug': 'travel-guides',
                    'post_count': 2,
                }
            ],
        )


class BlogAdminAPITests(TestCase):
    def setUp(self):
        self.staff = User.objects.create(
            username='content-editor',
            first_name='Content',
            last_name='Editor',
            is_staff=True,
            is_active=True,
        )
        self.regular_user = User.objects.create(
            username='traveler',
            is_active=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.staff)
        self.published_at = timezone.now() - timedelta(minutes=5)

    def payload(self, **overrides):
        payload = {
            'title': 'Planning a stress-free holiday',
            'excerpt': 'A clear framework for planning a memorable trip.',
            'content': '# Start early\n\nSet a budget and confirm your dates.',
            'category': 'Travel Planning',
            'tags': ['Holiday Tips', 'Family Travel'],
            'cover_image_url': 'https://images.example.com/holiday.jpg',
            'cover_image_alt': 'A family enjoying a beach holiday',
            'cover_image_caption': 'Plan early and travel calmly.',
            'status': BlogPost.STATUS_PUBLISHED,
            'is_featured': True,
            'published_at': self.published_at.isoformat(),
            'seo_title': 'How to plan a stress-free holiday',
            'meta_description': 'A practical holiday planning guide.',
        }
        payload.update(overrides)
        return payload

    def test_staff_endpoints_reject_anonymous_and_non_staff_users(self):
        anonymous = APIClient()
        regular = APIClient()
        regular.force_authenticate(self.regular_user)

        for client in (anonymous, regular):
            list_response = client.get('/api/travel-admin/blog/posts/')
            create_response = client.post(
                '/api/travel-admin/blog/posts/',
                self.payload(),
                format='json',
            )
            self.assertIn(list_response.status_code, (401, 403))
            self.assertIn(create_response.status_code, (401, 403))

    def test_staff_can_create_post_with_string_category_and_tag_array(self):
        response = self.client.post(
            '/api/travel-admin/blog/posts/',
            self.payload(tags=['Holiday Tips', 'holiday tips', 'Family Travel']),
            format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['slug'], 'planning-a-stress-free-holiday')
        self.assertEqual(response.data['category'], 'Travel Planning')
        self.assertEqual(
            response.data['tags'],
            ['Family Travel', 'Holiday Tips'],
        )
        self.assertEqual(response.data['author_name'], 'Content Editor')
        post = BlogPost.objects.get()
        self.assertEqual(post.author, self.staff)
        self.assertEqual(BlogCategory.objects.count(), 1)
        self.assertEqual(BlogTag.objects.count(), 2)

        public = APIClient().get(f'/api/blog/posts/{post.slug}/')
        self.assertEqual(public.status_code, 200, public.data)

    def test_scheduled_post_is_available_to_staff_but_not_public(self):
        future = timezone.now() + timedelta(days=3)
        response = self.client.post(
            '/api/travel-admin/blog/posts/',
            self.payload(
                title='A scheduled destination guide',
                published_at=future.isoformat(),
            ),
            format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        post = BlogPost.objects.get()
        staff_detail = self.client.get(
            f'/api/travel-admin/blog/posts/{post.pk}/'
        )
        public_detail = APIClient().get(f'/api/blog/posts/{post.slug}/')
        self.assertEqual(staff_detail.status_code, 200)
        self.assertEqual(public_detail.status_code, 404)

    def test_admin_validation_rejects_invalid_publication_and_content(self):
        missing_date = self.client.post(
            '/api/travel-admin/blog/posts/',
            self.payload(published_at=None),
            format='json',
        )
        raw_html = self.client.post(
            '/api/travel-admin/blog/posts/',
            self.payload(
                title='Unsafe article',
                content='<script>alert("unsafe")</script>',
            ),
            format='json',
        )

        self.assertEqual(missing_date.status_code, 400, missing_date.data)
        self.assertIn('published_at', missing_date.data)
        self.assertEqual(raw_html.status_code, 400, raw_html.data)
        self.assertIn('content', raw_html.data)

    def test_duplicate_slug_is_rejected_case_insensitively(self):
        first = self.client.post(
            '/api/travel-admin/blog/posts/',
            self.payload(slug='Holiday-Planning'),
            format='json',
        )
        duplicate = self.client.post(
            '/api/travel-admin/blog/posts/',
            self.payload(
                title='A second article',
                slug='holiday-planning',
            ),
            format='json',
        )

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(duplicate.status_code, 400, duplicate.data)
        self.assertIn('slug', duplicate.data)

    def test_staff_can_list_filter_update_and_delete_posts(self):
        created = self.client.post(
            '/api/travel-admin/blog/posts/',
            self.payload(status='draft', published_at=None),
            format='json',
        )
        self.assertEqual(created.status_code, 201, created.data)
        post = BlogPost.objects.get()

        listed = self.client.get(
            '/api/travel-admin/blog/posts/',
            {'status': 'draft', 'category': 'travel-planning'},
        )
        updated = self.client.patch(
            f'/api/travel-admin/blog/posts/{post.pk}/',
            {
                'category': 'Destination Guides',
                'tags': ['Nigeria'],
                'status': 'published',
                'published_at': self.published_at.isoformat(),
                'author_name': 'Spoofed Author',
            },
            format='json',
        )

        self.assertEqual(listed.status_code, 200, listed.data)
        self.assertEqual(listed.data['count'], 1)
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data['category'], 'Destination Guides')
        self.assertEqual(updated.data['tags'], ['Nigeria'])
        self.assertEqual(updated.data['author_name'], 'Content Editor')
        post.refresh_from_db()
        self.assertEqual(post.author, self.staff)

        deleted = self.client.delete(
            f'/api/travel-admin/blog/posts/{post.pk}/'
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(BlogPost.objects.filter(pk=post.pk).exists())

    def test_model_validation_protects_non_api_writes(self):
        category = BlogCategory.objects.create(name='News', slug='news')
        post = BlogPost(
            author=self.staff,
            category=category,
            title='Unsafe direct write',
            slug='unsafe-direct-write',
            excerpt='Validation also applies to Django admin forms.',
            content='<iframe src="https://example.com"></iframe>',
            cover_image_url='https://images.example.com/direct.jpg',
            cover_image_alt='Direct write cover',
            status=BlogPost.STATUS_PUBLISHED,
        )

        with self.assertRaises(DjangoValidationError) as error:
            post.full_clean()
        self.assertIn('content', error.exception.message_dict)
        self.assertIn('published_at', error.exception.message_dict)
