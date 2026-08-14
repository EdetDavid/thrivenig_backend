import re
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured


LOCAL_STORAGE_BACKEND = 'django.core.files.storage.FileSystemStorage'
B2_STORAGE_BACKEND = 'storages.backends.s3.S3Storage'
B2_CACHE_CONTROL = 'public, max-age=31536000, immutable'

_B2_BUCKET_RE = re.compile(r'^[a-z0-9][a-z0-9-]{4,61}[a-z0-9]$')
_B2_REGION_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
_B2_RESERVED_BUCKET_PREFIXES = (
    'b2-',
    'xn--',
    'sthree-',
    'amzn-s3-demo-',
)
_B2_RESERVED_BUCKET_SUFFIXES = (
    '-s3alias',
    '--ol-s3',
    '.mrap',
    '--x-s3',
    '--table-s3',
)


def _configuration_error(message):
    raise ImproperlyConfigured(f'Blog media storage: {message}')


def _validate_required_b2_values(values):
    missing = [name for name, value in values.items() if not value]
    if missing:
        _configuration_error(
            'set the following environment variables when '
            f'USE_B2_STORAGE=True: {", ".join(missing)}.'
        )


def _validate_bucket_name(bucket_name):
    if (
        not _B2_BUCKET_RE.fullmatch(bucket_name)
        or bucket_name.startswith(_B2_RESERVED_BUCKET_PREFIXES)
        or bucket_name.endswith(_B2_RESERVED_BUCKET_SUFFIXES)
    ):
        _configuration_error(
            'B2_BUCKET_NAME must be 6-63 characters, use only lowercase '
            'letters, numbers, and hyphens, begin and end with a letter or '
            'number, and avoid reserved S3 prefixes and suffixes.'
        )


def _validate_endpoint(endpoint, region_name):
    parsed = urlsplit(endpoint)
    expected_host = f's3.{region_name}.backblazeb2.com'
    try:
        port = parsed.port
    except ValueError:
        port = 'invalid'
    if (
        parsed.scheme != 'https'
        or parsed.hostname != expected_host
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ('', '/')
        or parsed.query
        or parsed.fragment
    ):
        _configuration_error(
            'B2_ENDPOINT must be an HTTPS Backblaze S3 endpoint matching '
            'B2_REGION_NAME, with no credentials, port, path, query, or '
            'fragment.'
        )
    return f'https://{expected_host}'


def _validate_public_base_url(public_base_url, *, bucket_name, endpoint):
    if not public_base_url:
        endpoint_host = urlsplit(endpoint).hostname
        return f'https://{bucket_name}.{endpoint_host}'

    parsed = urlsplit(public_base_url)
    try:
        port = parsed.port
    except ValueError:
        port = 'invalid'
    if (
        parsed.scheme != 'https'
        or not parsed.hostname
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(part in ('.', '..') for part in parsed.path.split('/'))
    ):
        _configuration_error(
            'B2_PUBLIC_BASE_URL must be an absolute HTTPS URL with no '
            'credentials, port, dot segments, query, or fragment.'
        )

    normalized_path = parsed.path.rstrip('/')
    return f'https://{parsed.netloc}{normalized_path}'


def _validate_signed_url_ttl(value):
    try:
        ttl = int(value)
    except (TypeError, ValueError):
        _configuration_error('B2_SIGNED_URL_TTL_SECONDS must be an integer.')
    if not 60 <= ttl <= 604_800:
        _configuration_error(
            'B2_SIGNED_URL_TTL_SECONDS must be between 60 and 604800.'
        )
    return ttl


def build_blog_media_storage_config(
    *,
    debug,
    use_b2_storage,
    key_id='',
    application_key='',
    bucket_name='',
    endpoint='',
    region_name='',
    public_base_url='',
    signed_url_ttl_seconds='3600',
):
    """Return the ``STORAGES['blog_media']`` definition.

    Blog upload URLs are stored inside published posts, so the B2 backend is
    deliberately configured for stable, unsigned reads from a public bucket.
    The separate application key is still required for all writes.
    """
    if not use_b2_storage:
        return {'BACKEND': LOCAL_STORAGE_BACKEND}

    values = {
        'B2_KEY_ID': key_id,
        'B2_APPLICATION_KEY': application_key,
        'B2_BUCKET_NAME': bucket_name,
        'B2_ENDPOINT': endpoint,
        'B2_REGION_NAME': region_name,
    }
    _validate_required_b2_values(values)

    if any(value != value.strip() for value in values.values()):
        _configuration_error(
            'B2 credentials and connection settings must not contain '
            'leading or trailing whitespace.'
        )
    if not _B2_REGION_RE.fullmatch(region_name):
        _configuration_error('B2_REGION_NAME has an invalid format.')

    _validate_bucket_name(bucket_name)
    normalized_endpoint = _validate_endpoint(endpoint, region_name)
    normalized_public_base_url = _validate_public_base_url(
        public_base_url.strip(),
        bucket_name=bucket_name,
        endpoint=normalized_endpoint,
    )
    # Retained as a validated setting for backward compatibility. It does not
    # drive blog URLs because those URLs are persisted and must never expire.
    _validate_signed_url_ttl(signed_url_ttl_seconds)

    public_parts = urlsplit(normalized_public_base_url)
    custom_domain = public_parts.netloc + public_parts.path
    return {
        'BACKEND': B2_STORAGE_BACKEND,
        'OPTIONS': {
            'access_key': key_id,
            'secret_key': application_key,
            'bucket_name': bucket_name,
            'endpoint_url': normalized_endpoint,
            'region_name': region_name,
            'signature_version': 's3v4',
            'addressing_style': 'virtual',
            'default_acl': None,
            'querystring_auth': False,
            'file_overwrite': False,
            'custom_domain': custom_domain,
            'url_protocol': 'https:',
            'object_parameters': {
                'CacheControl': B2_CACHE_CONTROL,
            },
        },
    }
