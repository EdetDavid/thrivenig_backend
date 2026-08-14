import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from base.roles import CONTENT_MANAGER_GROUP_NAME

from .models import BlogImage, BlogPost, BlogPostView
from .test_media_upload import LOCAL_TEST_STORAGES, image_upload


TRAVEL_ADMIN_POSTS = '/api/travel-admin/blog/posts/'
INSURANCE_ADMIN_POSTS = '/api/travel-admin/insurance-blog/posts/'


class BlogChannelIsolationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media_root = tempfile.mkdtemp(prefix='thrive-channel-media-')
        cls.media_settings = override_settings(
            MEDIA_ROOT=cls.media_root,
            MEDIA_URL='/media/',
            SERVE_MEDIA_FILES=True,
            USE_B2_STORAGE=False,
            STORAGES=LOCAL_TEST_STORAGES,
        )
        cls.media_settings.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.media_settings.disable()
        shutil.rmtree(cls.media_root, ignore_errors=True)

    def setUp(self):
        content_group, _ = Group.objects.get_or_create(
            name=CONTENT_MANAGER_GROUP_NAME
        )
        self.manager = User.objects.create_user(username='channel-manager')
        self.manager.groups.add(content_group)
        self.other_manager = User.objects.create_user(username='other-manager')
        self.other_manager.groups.add(content_group)
        self.staff = User.objects.create_user(
            username='channel-admin',
            is_staff=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        self.now = timezone.now() - timedelta(minutes=1)

    def payload(self, title, **overrides):
        payload = {
            'title': title,
            'slug': 'shared-slug',
            'excerpt': 'Useful guidance from the editorial team.',
            'content': '# Start here\n\nReview the important details.',
            'category': 'Guides',
            'tags': ['Planning'],
            'cover_image_url': 'https://images.example.com/guide.jpg',
            'cover_image_alt': 'A person reviewing useful information',
            'status': 'published',
            'is_featured': False,
            'published_at': self.now.isoformat(),
        }
        payload.update(overrides)
        return payload

    def create_pair(self):
        travel = self.client.post(
            TRAVEL_ADMIN_POSTS,
            self.payload('Travel guide'),
            format='json',
        )
        insurance = self.client.post(
            INSURANCE_ADMIN_POSTS,
            self.payload('Insurance guide'),
            format='json',
        )
        self.assertEqual(travel.status_code, 201, travel.data)
        self.assertEqual(insurance.status_code, 201, insurance.data)
        return travel.data, insurance.data

    def test_server_assigns_channel_and_allows_slug_reuse_across_channels(self):
        travel, insurance = self.create_pair()

        self.assertEqual(travel['channel'], BlogPost.CHANNEL_TRAVEL)
        self.assertEqual(insurance['channel'], BlogPost.CHANNEL_INSURANCE)
        self.assertEqual(travel['slug'], insurance['slug'])
        self.assertEqual(
            set(BlogPost.objects.values_list('channel', flat=True)),
            {'travel', 'insurance'},
        )

    def test_client_cannot_override_or_move_the_url_selected_channel(self):
        created = self.client.post(
            TRAVEL_ADMIN_POSTS,
            self.payload('Travel guide', channel='insurance'),
            format='json',
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data['channel'], 'travel')

        post = BlogPost.objects.get()
        changed = self.client.patch(
            f'{TRAVEL_ADMIN_POSTS}{post.pk}/',
            {'channel': 'insurance', 'title': 'Updated travel guide'},
            format='json',
        )

        self.assertEqual(changed.status_code, 200, changed.data)
        post.refresh_from_db()
        self.assertEqual(changed.data['channel'], 'travel')
        self.assertEqual(post.channel, 'travel')

    def test_public_list_detail_categories_and_views_are_channel_scoped(self):
        travel, insurance = self.create_pair()
        public = APIClient()

        travel_list = public.get('/api/blog/posts/')
        insurance_list = public.get('/api/insurance/blog/posts/')
        travel_detail = public.get(f"/api/blog/posts/{travel['slug']}/")
        insurance_detail = public.get(
            f"/api/insurance/blog/posts/{insurance['slug']}/"
        )
        travel_categories = public.get('/api/blog/categories/')
        insurance_categories = public.get('/api/insurance/blog/categories/')

        self.assertEqual(
            [row['title'] for row in travel_list.data['results']],
            ['Travel guide'],
        )
        self.assertEqual(
            [row['title'] for row in insurance_list.data['results']],
            ['Insurance guide'],
        )
        self.assertEqual(travel_detail.data['title'], 'Travel guide')
        self.assertEqual(insurance_detail.data['title'], 'Insurance guide')
        self.assertEqual(travel_categories.data[0]['post_count'], 1)
        self.assertEqual(insurance_categories.data[0]['post_count'], 1)

        travel_view = public.post(
            f"/api/blog/posts/{travel['slug']}/view/",
            {'visitor_id': 'same-browser-visitor'},
            format='json',
        )
        insurance_view = public.post(
            f"/api/insurance/blog/posts/{insurance['slug']}/views/",
            {'visitor_id': 'same-browser-visitor'},
            format='json',
        )
        self.assertEqual(travel_view.status_code, 201, travel_view.data)
        self.assertEqual(insurance_view.status_code, 201, insurance_view.data)
        self.assertEqual(BlogPostView.objects.count(), 2)

    def test_admin_crud_and_analytics_never_cross_channels(self):
        travel, insurance = self.create_pair()

        travel_list = self.client.get(TRAVEL_ADMIN_POSTS)
        insurance_list = self.client.get(INSURANCE_ADMIN_POSTS)
        wrong_travel_detail = self.client.get(
            f"{TRAVEL_ADMIN_POSTS}{insurance['id']}/"
        )
        wrong_insurance_detail = self.client.get(
            f"{INSURANCE_ADMIN_POSTS}{travel['id']}/"
        )
        travel_analytics = self.client.get(
            '/api/travel-admin/blog/analytics/'
        )
        insurance_analytics = self.client.get(
            '/api/travel-admin/insurance-blog/analytics/'
        )

        self.assertEqual(travel_list.data['count'], 1)
        self.assertEqual(insurance_list.data['count'], 1)
        self.assertEqual(wrong_travel_detail.status_code, 404)
        self.assertEqual(wrong_insurance_detail.status_code, 404)
        self.assertEqual(travel_analytics.data['summary']['posts'], 1)
        self.assertEqual(insurance_analytics.data['summary']['posts'], 1)
        self.assertEqual(travel_analytics.data['summary']['total_views'], 0)
        self.assertEqual(
            insurance_analytics.data['summary']['total_views'],
            0,
        )

    def test_content_manager_author_scope_applies_inside_each_channel(self):
        self.create_pair()
        other_client = APIClient()
        other_client.force_authenticate(self.other_manager)
        other = other_client.post(
            INSURANCE_ADMIN_POSTS,
            self.payload('Other insurance guide', slug='other-insurance'),
            format='json',
        )
        self.assertEqual(other.status_code, 201, other.data)

        manager_insurance = self.client.get(INSURANCE_ADMIN_POSTS)
        manager_wrong_detail = self.client.get(
            f"{INSURANCE_ADMIN_POSTS}{other.data['id']}/"
        )
        staff_client = APIClient()
        staff_client.force_authenticate(self.staff)
        staff_insurance = staff_client.get(INSURANCE_ADMIN_POSTS)

        self.assertEqual(manager_insurance.data['count'], 1)
        self.assertEqual(manager_wrong_detail.status_code, 404)
        self.assertEqual(staff_insurance.data['count'], 2)

    def test_image_uploads_are_owned_by_the_url_selected_channel(self):
        travel = self.client.post(
            '/api/travel-admin/blog/media/images/',
            {'image': image_upload()},
            format='multipart',
        )
        insurance = self.client.post(
            '/api/travel-admin/insurance-blog/media/images/',
            {'image': image_upload()},
            format='multipart',
        )

        self.assertEqual(travel.status_code, 201, travel.data)
        self.assertEqual(insurance.status_code, 201, insurance.data)
        self.assertIn('/blog/travel/images/', travel.data['url'])
        self.assertIn('/blog/insurance/images/', insurance.data['url'])
        self.assertEqual(
            set(BlogImage.objects.values_list('channel', flat=True)),
            {'travel', 'insurance'},
        )

    def test_existing_travel_response_shape_is_unchanged(self):
        travel, _ = self.create_pair()
        public_row = APIClient().get('/api/blog/posts/').data['results'][0]

        self.assertNotIn('channel', public_row)
        self.assertEqual(travel['channel'], 'travel')
