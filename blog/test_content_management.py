from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from base.roles import CONTENT_MANAGER_GROUP_NAME

from .models import BlogCategory, BlogPost, BlogPostView
from .views import hash_visitor_identifier


class ContentManagementFixture:
    def setUp(self):
        group, _ = Group.objects.get_or_create(
            name=CONTENT_MANAGER_GROUP_NAME
        )
        self.manager = User.objects.create_user(
            username='content-manager',
            first_name='Content',
            last_name='Manager',
        )
        self.manager.groups.add(group)
        self.other_manager = User.objects.create_user(
            username='other-manager'
        )
        self.other_manager.groups.add(group)
        self.regular_user = User.objects.create_user(username='traveler')
        self.staff = User.objects.create_user(
            username='travel-admin',
            is_staff=True,
        )
        self.category = BlogCategory.objects.create(
            name='Travel Guides',
            slug='travel-guides',
        )
        self.now = timezone.now()
        self.own_post = self.create_post(
            author=self.manager,
            title='Manager story',
            slug='manager-story',
            status=BlogPost.STATUS_PUBLISHED,
            published_at=self.now - timedelta(days=20),
        )
        self.own_draft = self.create_post(
            author=self.manager,
            title='Manager draft',
            slug='manager-draft',
            status=BlogPost.STATUS_DRAFT,
        )
        self.other_post = self.create_post(
            author=self.other_manager,
            title='Other story',
            slug='other-story',
            status=BlogPost.STATUS_PUBLISHED,
            published_at=self.now - timedelta(days=3),
        )
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def create_post(self, **overrides):
        values = {
            'category': self.category,
            'excerpt': 'Useful travel advice for thoughtful journeys.',
            'content': '# Plan well\n\nConfirm every important detail.',
            'cover_image_url': 'https://images.example.com/travel.jpg',
            'cover_image_alt': 'A thoughtful traveler',
        }
        values.update(overrides)
        return BlogPost.objects.create(**values)

    def draft_payload(self):
        return {
            'title': 'A newly authored guide',
            'excerpt': 'A useful guide created in the content studio.',
            'content': '# Start here\n\nPrepare the important details.',
            'category': 'Travel Planning',
            'tags': ['Planning'],
            'cover_image_url': 'https://images.example.com/new-guide.jpg',
            'cover_image_alt': 'A traveler planning a trip',
            'status': 'draft',
            'is_featured': False,
            'published_at': None,
        }


class ContentManagementAPITests(ContentManagementFixture, TestCase):

    def test_content_manager_crud_is_author_scoped_and_stamps_author(self):
        listed = self.client.get('/api/travel-admin/blog/posts/')
        own_detail = self.client.get(
            f'/api/travel-admin/blog/posts/{self.own_post.pk}/'
        )
        other_detail = self.client.get(
            f'/api/travel-admin/blog/posts/{self.other_post.pk}/'
        )
        other_update = self.client.patch(
            f'/api/travel-admin/blog/posts/{self.other_post.pk}/',
            {'title': 'Attempted overwrite'},
            format='json',
        )
        other_delete = self.client.delete(
            f'/api/travel-admin/blog/posts/{self.other_post.pk}/'
        )
        created = self.client.post(
            '/api/travel-admin/blog/posts/',
            self.draft_payload(),
            format='json',
        )

        self.assertEqual(listed.status_code, 200, listed.data)
        self.assertEqual(listed.data['count'], 2)
        self.assertEqual(
            {row['id'] for row in listed.data['results']},
            {self.own_post.pk, self.own_draft.pk},
        )
        self.assertEqual(own_detail.status_code, 200, own_detail.data)
        self.assertEqual(other_detail.status_code, 404, other_detail.data)
        self.assertEqual(other_update.status_code, 404, other_update.data)
        self.assertEqual(other_delete.status_code, 404, other_delete.data)
        self.assertEqual(created.status_code, 201, created.data)
        new_post = BlogPost.objects.get(title='A newly authored guide')
        self.assertEqual(new_post.author, self.manager)
        self.other_post.refresh_from_db()
        self.assertEqual(self.other_post.title, 'Other story')

    def test_content_manager_cannot_open_other_travel_admin_apis(self):
        response = self.client.get('/api/travel-admin/overview/')
        users = self.client.get('/api/travel-admin/users/')

        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(users.status_code, 403, users.data)

    def test_content_manager_can_publish_a_post_that_is_immediately_public(self):
        payload = self.draft_payload()
        payload.update(
            status=BlogPost.STATUS_PUBLISHED,
            published_at=(timezone.now() - timedelta(seconds=1)).isoformat(),
        )

        created = self.client.post(
            '/api/travel-admin/blog/posts/',
            payload,
            format='json',
        )

        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data['status'], BlogPost.STATUS_PUBLISHED)
        public_list = APIClient().get('/api/blog/posts/')
        public_detail = APIClient().get(
            f"/api/blog/posts/{created.data['slug']}/"
        )
        self.assertEqual(public_list.status_code, 200, public_list.data)
        self.assertIn(
            created.data['slug'],
            [row['slug'] for row in public_list.data['results']],
        )
        self.assertEqual(public_detail.status_code, 200, public_detail.data)
        self.assertEqual(public_detail.data['title'], payload['title'])

    def test_regular_user_cannot_open_content_endpoints_and_staff_sees_all(self):
        regular = APIClient()
        regular.force_authenticate(self.regular_user)
        denied_posts = regular.get('/api/travel-admin/blog/posts/')
        denied_analytics = regular.get('/api/travel-admin/blog/analytics/')

        self.assertEqual(denied_posts.status_code, 403, denied_posts.data)
        self.assertEqual(
            denied_analytics.status_code,
            403,
            denied_analytics.data,
        )

        staff_client = APIClient()
        staff_client.force_authenticate(self.staff)
        posts = staff_client.get('/api/travel-admin/blog/posts/')
        analytics = staff_client.get('/api/travel-admin/blog/analytics/')
        self.assertEqual(posts.status_code, 200, posts.data)
        self.assertEqual(posts.data['count'], 3)
        self.assertEqual(analytics.status_code, 200, analytics.data)
        self.assertEqual(analytics.data['scope'], 'all')
        self.assertEqual(analytics.data['summary']['posts'], 3)


class BlogViewTrackingTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(username='view-author')
        self.category = BlogCategory.objects.create(
            name='Destinations',
            slug='destinations',
        )
        self.post = BlogPost.objects.create(
            author=self.author,
            category=self.category,
            title='A public destination story',
            slug='public-destination-story',
            excerpt='A detailed destination guide.',
            content='Practical destination advice.',
            cover_image_url='https://images.example.com/destination.jpg',
            cover_image_alt='A beautiful destination',
            status=BlogPost.STATUS_PUBLISHED,
            published_at=timezone.now() - timedelta(days=1),
        )
        self.draft = BlogPost.objects.create(
            author=self.author,
            category=self.category,
            title='A private draft',
            slug='private-draft',
            excerpt='Not yet public.',
            content='Draft destination advice.',
            cover_image_url='https://images.example.com/draft.jpg',
            cover_image_alt='A draft cover',
            status=BlogPost.STATUS_DRAFT,
        )

    def test_explicit_view_post_hashes_and_deduplicates_visitors(self):
        client = APIClient()
        detail = client.get(f'/api/blog/posts/{self.post.slug}/')
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(BlogPostView.objects.count(), 0)

        first = client.post(
            f'/api/blog/posts/{self.post.slug}/view/',
            {'visitor_id': 'browser-visitor-123'},
            format='json',
        )
        duplicate = client.post(
            f'/api/blog/posts/{self.post.slug}/view/',
            {'visitor_id': 'browser-visitor-123'},
            format='json',
        )
        another = client.post(
            f'/api/blog/posts/{self.post.slug}/view/',
            {'visitor_id': 'browser-visitor-456'},
            format='json',
        )

        self.assertEqual(first.status_code, 201, first.data)
        self.assertTrue(first.data['recorded'])
        self.assertEqual(duplicate.status_code, 200, duplicate.data)
        self.assertFalse(duplicate.data['recorded'])
        self.assertEqual(another.status_code, 201, another.data)
        self.assertEqual(BlogPostView.objects.count(), 2)
        stored_hashes = list(
            BlogPostView.objects.values_list('visitor_hash', flat=True)
        )
        self.assertTrue(all(len(value) == 64 for value in stored_hashes))
        self.assertNotIn('browser-visitor-123', stored_hashes)

    def test_view_post_rejects_invalid_or_non_public_requests(self):
        client = APIClient()
        missing_visitor = client.post(
            f'/api/blog/posts/{self.post.slug}/view/',
            {},
            format='json',
        )
        private_post = client.post(
            f'/api/blog/posts/{self.draft.slug}/view/',
            {'visitor_id': 'browser-visitor-123'},
            format='json',
        )

        self.assertEqual(missing_visitor.status_code, 400)
        self.assertEqual(private_post.status_code, 404)
        self.assertEqual(BlogPostView.objects.count(), 0)


class BlogAnalyticsAPITests(ContentManagementFixture, TestCase):
    def setUp(self):
        super().setUp()
        BlogPostView.objects.bulk_create(
            [
                BlogPostView(
                    post=self.own_post,
                    visitor_hash=hash_visitor_identifier('visitor-a'),
                    viewed_at=self.now - timedelta(days=1),
                ),
                BlogPostView(
                    post=self.own_post,
                    visitor_hash=hash_visitor_identifier('visitor-a'),
                    viewed_at=self.now - timedelta(days=2),
                ),
                BlogPostView(
                    post=self.own_post,
                    visitor_hash=hash_visitor_identifier('visitor-b'),
                    viewed_at=self.now - timedelta(days=10),
                ),
                BlogPostView(
                    post=self.other_post,
                    visitor_hash=hash_visitor_identifier('visitor-c'),
                    viewed_at=self.now - timedelta(days=1),
                ),
            ]
        )

    def test_content_analytics_matches_contract_and_is_author_scoped(self):
        response = self.client.get(
            '/api/travel-admin/blog/analytics/',
            {'days': 7},
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['period_days'], 7)
        self.assertEqual(response.data['scope'], 'author')
        self.assertEqual(
            response.data['summary'],
            {
                'posts': 2,
                'published': 1,
                'drafts': 1,
                'archived': 0,
                'total_views': 3,
                'unique_viewers': 2,
                'period_views': 2,
                'period_unique_viewers': 1,
            },
        )
        self.assertEqual(len(response.data['daily_views']), 7)
        self.assertEqual(
            sum(day['views'] for day in response.data['daily_views']),
            2,
        )
        own_metrics = next(
            row
            for row in response.data['posts']
            if row['id'] == self.own_post.pk
        )
        self.assertEqual(own_metrics['total_views'], 3)
        self.assertEqual(own_metrics['unique_viewers'], 2)
        self.assertEqual(own_metrics['period_views'], 2)
        self.assertEqual(own_metrics['period_unique_viewers'], 1)
        self.assertNotIn(
            self.other_post.pk,
            {row['id'] for row in response.data['posts']},
        )

    def test_all_period_and_validation_are_supported(self):
        all_time = self.client.get(
            '/api/travel-admin/blog/analytics/',
            {'days': 'all'},
        )
        invalid = self.client.get(
            '/api/travel-admin/blog/analytics/',
            {'days': 366},
        )

        self.assertEqual(all_time.status_code, 200, all_time.data)
        self.assertEqual(all_time.data['period_days'], 'all')
        self.assertEqual(all_time.data['summary']['period_views'], 3)
        self.assertEqual(
            all_time.data['summary']['period_unique_viewers'],
            2,
        )
        self.assertEqual(invalid.status_code, 400, invalid.data)
