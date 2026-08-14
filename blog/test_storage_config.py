from unittest.mock import patch

from django.core.checks import Tags, run_checks
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage, storages
from django.test import SimpleTestCase, override_settings

from backend.storage_config import (
    B2_CACHE_CONTROL,
    B2_STORAGE_BACKEND,
    LOCAL_STORAGE_BACKEND,
    build_blog_media_storage_config,
)
from base.models import Claim, SubmitCv

from .models import BlogImage
from .test_media_upload import LOCAL_TEST_STORAGES


VALID_B2 = {
    'debug': False,
    'use_b2_storage': True,
    'key_id': 'test-key-id',
    'application_key': 'test-application-key',
    'bucket_name': 'thrive-blog-media',
    'endpoint': 'https://s3.us-west-004.backblazeb2.com',
    'region_name': 'us-west-004',
    'signed_url_ttl_seconds': '3600',
}


class BlogMediaStorageConfigurationTests(SimpleTestCase):
    def test_local_filesystem_remains_available_regardless_of_debug(self):
        for debug in (True, False):
            with self.subTest(debug=debug):
                config = build_blog_media_storage_config(
                    debug=debug,
                    use_b2_storage=False,
                )
                self.assertEqual(config, {'BACKEND': LOCAL_STORAGE_BACKEND})

    def test_b2_configuration_is_explicit_public_and_backblaze_specific(self):
        config = build_blog_media_storage_config(**VALID_B2)

        self.assertEqual(config['BACKEND'], B2_STORAGE_BACKEND)
        self.assertEqual(
            config['OPTIONS'],
            {
                'access_key': 'test-key-id',
                'secret_key': 'test-application-key',
                'bucket_name': 'thrive-blog-media',
                'endpoint_url': (
                    'https://s3.us-west-004.backblazeb2.com'
                ),
                'region_name': 'us-west-004',
                'signature_version': 's3v4',
                'addressing_style': 'virtual',
                'default_acl': None,
                'querystring_auth': False,
                'file_overwrite': False,
                'custom_domain': (
                    'thrive-blog-media.s3.us-west-004.backblazeb2.com'
                ),
                'url_protocol': 'https:',
                'object_parameters': {
                    'CacheControl': B2_CACHE_CONTROL,
                },
            },
        )

    def test_b2_backend_builds_a_stable_unsigned_url_without_network_io(self):
        config = build_blog_media_storage_config(**VALID_B2)

        with patch(
            'botocore.client.BaseClient._make_api_call',
            side_effect=AssertionError('network access is forbidden'),
        ):
            storage = storages.create_storage(config)
            url = storage.url('blog/travel/images/2026/08/example.png')

        self.assertEqual(
            url,
            'https://thrive-blog-media.s3.us-west-004.backblazeb2.com/'
            'blog/travel/images/2026/08/example.png',
        )
        self.assertNotIn('?', url)

    def test_optional_public_base_url_is_used_without_a_trailing_slash(self):
        config = build_blog_media_storage_config(
            **VALID_B2,
            public_base_url='https://media.example.com/thrive-blog/',
        )

        self.assertEqual(
            config['OPTIONS']['custom_domain'],
            'media.example.com/thrive-blog',
        )

    def test_missing_values_are_named_without_echoing_credentials(self):
        invalid = {
            **VALID_B2,
            'application_key': '',
            'bucket_name': '',
        }

        with self.assertRaises(ImproperlyConfigured) as raised:
            build_blog_media_storage_config(**invalid)

        message = str(raised.exception)
        self.assertIn('B2_APPLICATION_KEY', message)
        self.assertIn('B2_BUCKET_NAME', message)
        self.assertNotIn(VALID_B2['key_id'], message)

    def test_invalid_endpoint_bucket_public_url_and_ttl_are_rejected(self):
        cases = (
            (
                {'endpoint': 'http://s3.us-west-004.backblazeb2.com'},
                'B2_ENDPOINT',
            ),
            (
                {'endpoint': 'https://s3.eu-central-003.backblazeb2.com'},
                'B2_ENDPOINT',
            ),
            ({'bucket_name': 'Invalid.Bucket'}, 'B2_BUCKET_NAME'),
            (
                {'public_base_url': 'http://media.example.com'},
                'B2_PUBLIC_BASE_URL',
            ),
            (
                {'public_base_url': 'https://media.example.com:8443/blog'},
                'B2_PUBLIC_BASE_URL',
            ),
            ({'signed_url_ttl_seconds': '59'}, 'B2_SIGNED_URL_TTL_SECONDS'),
        )

        for overrides, expected_name in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ImproperlyConfigured) as raised:
                    build_blog_media_storage_config(
                        **{**VALID_B2, **overrides}
                    )
                self.assertIn(expected_name, str(raised.exception))
                self.assertNotIn(
                    VALID_B2['application_key'],
                    str(raised.exception),
                )

    @override_settings(
        USE_B2_STORAGE=False,
        SERVE_MEDIA_FILES=True,
        STORAGES=LOCAL_TEST_STORAGES,
    )
    def test_blog_images_use_dedicated_alias_but_sensitive_files_use_default(self):
        blog_storage = BlogImage._meta.get_field('image').storage
        claim_storage = Claim._meta.get_field('file').storage
        cv_storage = SubmitCv._meta.get_field('cv').storage

        self.assertIsInstance(blog_storage, FileSystemStorage)
        self.assertIsInstance(claim_storage, FileSystemStorage)
        self.assertIsInstance(cv_storage, FileSystemStorage)
        self.assertIs(blog_storage._wrapped, storages['blog_media'])
        self.assertIsNot(blog_storage._wrapped, storages['default'])

    @override_settings(USE_B2_STORAGE=False, SERVE_MEDIA_FILES=True)
    def test_deployment_checks_warn_about_local_blog_media(self):
        issues = run_checks(tags=[Tags.security], include_deployment_checks=True)
        ids = {issue.id for issue in issues}

        self.assertIn('blog.W001', ids)
        self.assertIn('blog.W002', ids)
