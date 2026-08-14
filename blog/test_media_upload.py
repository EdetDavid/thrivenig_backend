import shutil
import tempfile
from io import BytesIO
from urllib.parse import urlsplit

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from base.roles import CONTENT_MANAGER_GROUP_NAME

from .models import BlogImage


UPLOAD_URL = '/api/travel-admin/blog/media/images/'
LOCAL_TEST_STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'blog_media': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}


def image_upload(
    image_format='PNG',
    *,
    content_type='image/png',
    size=(3, 2),
    name='cover.png',
):
    output = BytesIO()
    image = Image.new('RGB', size, color=(18, 52, 86))
    image.save(output, format=image_format)
    return SimpleUploadedFile(
        name,
        output.getvalue(),
        content_type=content_type,
    )


class BlogImageUploadAPITests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media_root = tempfile.mkdtemp(prefix='thrive-blog-media-')
        cls.media_settings = override_settings(
            MEDIA_ROOT=cls.media_root,
            MEDIA_URL='/media/',
            SERVE_MEDIA_FILES=True,
            USE_B2_STORAGE=False,
            STORAGES=LOCAL_TEST_STORAGES,
            BLOG_IMAGE_MAX_SIZE_BYTES=5 * 1024 * 1024,
            BLOG_IMAGE_MAX_PIXELS=40_000_000,
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
        self.manager = User.objects.create_user(username='content-manager')
        self.manager.groups.add(content_group)
        self.staff = User.objects.create_user(
            username='travel-admin',
            is_staff=True,
        )
        self.traveler = User.objects.create_user(username='traveler')
        self.client = APIClient()

    def authenticate(self, user=None):
        self.client.force_authenticate(user or self.manager)

    def test_content_manager_can_upload_and_fetch_an_image(self):
        self.authenticate()

        response = self.client.post(
            UPLOAD_URL,
            {'image': image_upload()},
            format='multipart',
            HTTP_HOST='localhost',
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            set(response.data),
            {'url', 'width', 'height', 'content_type', 'size_bytes'},
        )
        self.assertRegex(
            response.data['url'],
            r'^http://localhost/media/blog/travel/images/\d{4}/\d{2}/'
            r'[0-9a-f]{32}\.png$',
        )
        self.assertEqual(response.data['width'], 3)
        self.assertEqual(response.data['height'], 2)
        self.assertEqual(response.data['content_type'], 'image/png')
        self.assertGreater(response.data['size_bytes'], 0)

        stored = BlogImage.objects.get()
        self.assertEqual(stored.uploaded_by, self.manager)
        self.assertEqual(stored.width, 3)
        self.assertEqual(stored.height, 2)
        self.assertEqual(stored.content_type, 'image/png')
        self.assertEqual(stored.size_bytes, response.data['size_bytes'])
        self.assertTrue(stored.image.storage.exists(stored.image.name))

        public_path = urlsplit(response.data['url']).path
        fetched = APIClient().get(public_path)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched['Content-Type'], 'image/png')
        self.assertEqual(
            b''.join(fetched.streaming_content),
            stored.image.read(),
        )

    def test_staff_can_upload_each_supported_static_format(self):
        self.authenticate(self.staff)
        cases = (
            ('JPEG', 'image/jpeg', 'cover.jpeg', '.jpg'),
            ('PNG', 'image/png', 'cover.png', '.png'),
            ('WEBP', 'image/webp', 'cover.webp', '.webp'),
            ('GIF', 'image/gif', 'cover.gif', '.gif'),
        )

        for image_format, content_type, name, stored_extension in cases:
            with self.subTest(image_format=image_format):
                response = self.client.post(
                    UPLOAD_URL,
                    {
                        'image': image_upload(
                            image_format,
                            content_type=content_type,
                            name=name,
                        )
                    },
                    format='multipart',
                )
                self.assertEqual(response.status_code, 201, response.data)
                self.assertEqual(response.data['content_type'], content_type)
                self.assertTrue(
                    urlsplit(response.data['url']).path.endswith(
                        stored_extension
                    )
                )

        self.assertEqual(BlogImage.objects.count(), len(cases))

    def test_upload_requires_an_active_content_manager_or_staff_user(self):
        anonymous = self.client.post(
            UPLOAD_URL,
            {'image': image_upload()},
            format='multipart',
        )
        self.authenticate(self.traveler)
        traveler = self.client.post(
            UPLOAD_URL,
            {'image': image_upload()},
            format='multipart',
        )
        self.manager.is_active = False
        self.manager.save(update_fields=['is_active'])
        self.authenticate(self.manager)
        inactive_manager = self.client.post(
            UPLOAD_URL,
            {'image': image_upload()},
            format='multipart',
        )

        self.assertIn(anonymous.status_code, (401, 403))
        self.assertEqual(traveler.status_code, 403)
        self.assertEqual(inactive_manager.status_code, 403)
        self.assertEqual(BlogImage.objects.count(), 0)

    def test_upload_rejects_missing_oversized_and_unreadable_files(self):
        self.authenticate()
        missing = self.client.post(UPLOAD_URL, {}, format='multipart')
        oversized = self.client.post(
            UPLOAD_URL,
            {
                'image': SimpleUploadedFile(
                    'too-large.png',
                    b'x' * (5 * 1024 * 1024 + 1),
                    content_type='image/png',
                )
            },
            format='multipart',
        )
        unreadable = self.client.post(
            UPLOAD_URL,
            {
                'image': SimpleUploadedFile(
                    'fake.png',
                    b'not a real image',
                    content_type='image/png',
                )
            },
            format='multipart',
        )

        self.assertEqual(missing.status_code, 400, missing.data)
        self.assertIn('image', missing.data)
        self.assertEqual(oversized.status_code, 400, oversized.data)
        self.assertEqual(
            str(oversized.data['image'][0]),
            'Image files must be 5 MiB or smaller.',
        )
        self.assertEqual(unreadable.status_code, 400, unreadable.data)
        self.assertEqual(
            str(unreadable.data['image'][0]),
            'Upload a valid, readable image file.',
        )
        self.assertEqual(BlogImage.objects.count(), 0)

    def test_upload_rejects_unsupported_or_mismatched_image_types(self):
        self.authenticate()
        unsupported = self.client.post(
            UPLOAD_URL,
            {
                'image': image_upload(
                    'BMP',
                    content_type='image/bmp',
                    name='cover.bmp',
                )
            },
            format='multipart',
        )
        mismatched = self.client.post(
            UPLOAD_URL,
            {
                'image': image_upload(
                    'PNG',
                    content_type='image/jpeg',
                    name='cover.jpg',
                )
            },
            format='multipart',
        )

        self.assertEqual(unsupported.status_code, 400, unsupported.data)
        self.assertEqual(
            str(unsupported.data['image'][0]),
            'Upload a JPEG, PNG, WebP, or GIF image.',
        )
        self.assertEqual(mismatched.status_code, 400, mismatched.data)
        self.assertEqual(
            str(mismatched.data['image'][0]),
            'The uploaded file type does not match its image content.',
        )
        self.assertEqual(BlogImage.objects.count(), 0)

    def test_upload_rejects_animated_gifs_and_excessive_dimensions(self):
        self.authenticate()
        output = BytesIO()
        frames = [
            Image.new('RGB', (2, 2), color=color)
            for color in ((255, 0, 0), (0, 0, 255))
        ]
        frames[0].save(
            output,
            format='GIF',
            save_all=True,
            append_images=frames[1:],
            duration=100,
            loop=0,
        )
        animated = self.client.post(
            UPLOAD_URL,
            {
                'image': SimpleUploadedFile(
                    'animated.gif',
                    output.getvalue(),
                    content_type='image/gif',
                )
            },
            format='multipart',
        )
        with override_settings(BLOG_IMAGE_MAX_PIXELS=3):
            excessive_dimensions = self.client.post(
                UPLOAD_URL,
                {'image': image_upload(size=(2, 2))},
                format='multipart',
            )

        self.assertEqual(animated.status_code, 400, animated.data)
        self.assertEqual(
            str(animated.data['image'][0]),
            'Animated images are not supported.',
        )
        self.assertEqual(
            excessive_dimensions.status_code,
            400,
            excessive_dimensions.data,
        )
        self.assertEqual(
            str(excessive_dimensions.data['image'][0]),
            'Image dimensions are too large.',
        )
        self.assertEqual(BlogImage.objects.count(), 0)

    @override_settings(SERVE_MEDIA_FILES=False)
    def test_local_media_route_is_disabled_when_not_configured(self):
        response = APIClient().get('/media/blog/images/example.png')

        self.assertEqual(response.status_code, 404)
