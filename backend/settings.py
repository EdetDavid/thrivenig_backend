from pathlib import Path
import os
import environ

# Initialize environment variables
env = environ.Env(
    # Set casting and default values
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1", ".vercel.app"]),
    CORS_ALLOW_ALL_ORIGINS=(bool, False),
)

# Take environment variables from the .env file
environ.Env.read_env(os.path.join(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))), '.env'))


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env.bool('DEBUG', default=False)
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=env.list('HOSTS', default=["localhost", "127.0.0.1", ".vercel.app"]))
if DEBUG:
    ALLOWED_HOSTS = list(dict.fromkeys([
        *ALLOWED_HOSTS,
        'localhost',
        '127.0.0.1',
    ]))


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "blog.apps.BlogConfig",
    "base.apps.BaseConfig",
    'corsheaders',
    'rest_framework',
    "rest_framework.authtoken",
    "django_ses",
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",

]

ROOT_URLCONF = "backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        'DIRS': [BASE_DIR, "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "backend.wsgi.application"


# Server-side flight search. Never expose supplier tokens to the React app.
FLIGHT_SEARCH_PROVIDER = env('FLIGHT_SEARCH_PROVIDER', default='')
DUFFEL_ACCESS_TOKEN = env('DUFFEL_ACCESS_TOKEN', default='')
DUFFEL_API_BASE_URL = env(
    'DUFFEL_API_BASE_URL',
    default='https://api.duffel.com',
)
DUFFEL_API_VERSION = env('DUFFEL_API_VERSION', default='v2')
DUFFEL_SUPPLIER_TIMEOUT_MS = env.int(
    'DUFFEL_SUPPLIER_TIMEOUT_MS',
    default=15000,
)
FLIGHT_SEARCH_TIMEOUT_SECONDS = env.int(
    'FLIGHT_SEARCH_TIMEOUT_SECONDS',
    default=25,
)
FLIGHT_SEARCH_RELAX_TLS_STRICT = env.bool(
    'FLIGHT_SEARCH_RELAX_TLS_STRICT',
    default=False,
)
FLIGHT_SEARCH_CACHE_SECONDS = env.int(
    'FLIGHT_SEARCH_CACHE_SECONDS',
    default=120,
)
FLIGHT_SEARCH_RESULT_LIMIT = min(
    max(env.int('FLIGHT_SEARCH_RESULT_LIMIT', default=50), 1),
    200,
)
FLIGHT_LOCATION_CACHE_SECONDS = env.int(
    'FLIGHT_LOCATION_CACHE_SECONDS',
    default=3600,
)
ALLOW_DUFFEL_TEST_DATA = env.bool(
    'ALLOW_DUFFEL_TEST_DATA',
    default=DEBUG,
)

# Hotel search can use inventory curated by Thrive staff or Duffel Stays.
# Supplier tokens remain server-side and must never be sent to the React app.
HOTEL_SEARCH_PROVIDER = env('HOTEL_SEARCH_PROVIDER', default='local')
ALLOW_HOTEL_TEST_DATA = env.bool(
    'ALLOW_HOTEL_TEST_DATA',
    default=DEBUG,
)
HOTEL_SEARCH_TIMEOUT_SECONDS = env.int(
    'HOTEL_SEARCH_TIMEOUT_SECONDS',
    default=30,
)
HOTEL_SEARCH_RELAX_TLS_STRICT = env.bool(
    'HOTEL_SEARCH_RELAX_TLS_STRICT',
    default=False,
)
HOTEL_SEARCH_CACHE_SECONDS = env.int(
    'HOTEL_SEARCH_CACHE_SECONDS',
    default=300,
)
HOTEL_SEARCH_RESULT_LIMIT = min(
    max(env.int('HOTEL_SEARCH_RESULT_LIMIT', default=50), 1),
    200,
)
HOTEL_LOCATION_CACHE_SECONDS = env.int(
    'HOTEL_LOCATION_CACHE_SECONDS',
    default=3600,
)
HOTEL_SEARCH_DEFAULT_RADIUS_KM = min(
    max(env.int('HOTEL_SEARCH_DEFAULT_RADIUS_KM', default=10), 1),
    100,
)
HOTEL_FX_API_BASE_URL = env(
    'HOTEL_FX_API_BASE_URL',
    default='https://api.frankfurter.dev/v2',
)
HOTEL_FX_TIMEOUT_SECONDS = env.int(
    'HOTEL_FX_TIMEOUT_SECONDS',
    default=5,
)
HOTEL_FX_CACHE_SECONDS = env.int(
    'HOTEL_FX_CACHE_SECONDS',
    default=86400,
)
DRF_NUM_PROXIES = env.int('DRF_NUM_PROXIES', default=0)

# OpenAI chatbot credentials must be configured as server environment variables.
OPENAI_API_KEY = env('OPENAI_API_KEY', default='')
OPENAI_CHAT_MODEL = env('OPENAI_CHAT_MODEL', default='gpt-5.6-terra')


# Email configuration — prefer SES when credentials are present, otherwise use console backend to avoid runtime errors
# If you want to enable SES, set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in your .env
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='thriveholdingswebmail@gmail.com')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default=EMAIL_HOST_USER or 'thriveholdingswebmail@gmail.com')
# Recipient groups are configured as comma-separated environment variables.
ADMIN_EMAILS = env.list('ADMIN_EMAILS', default=[])
TRAVEL_AGENCY_EMAILS = env.list('TRAVEL_AGENCY_EMAILS', default=[])
INSURANCE_AGENCY_EMAILS = env.list('INSURANCE_AGENCY_EMAILS', default=[])

# AWS credentials and SES-specific settings. Prefer environment variables (do NOT commit credentials).
AWS_ACCESS_KEY_ID = env('AWS_ACCESS_KEY_ID', default='')
AWS_SECRET_ACCESS_KEY = env('AWS_SECRET_ACCESS_KEY', default='')
# Example region: 'us-east-1'
AWS_SES_REGION_NAME = env('AWS_SES_REGION_NAME', default='us-east-1')
# Example endpoint: 'email.us-east-1.amazonaws.com'
AWS_SES_REGION_ENDPOINT = env('AWS_SES_REGION_ENDPOINT', default=f'email.{AWS_SES_REGION_NAME}.amazonaws.com')

# Select email backend: use django-ses only when AWS creds are provided; otherwise fall back to console backend
if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
    EMAIL_BACKEND = 'django_ses.SESBackend'
else:
    # Safe default for development: prints email to console and prevents SES API calls
    EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')

# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases


DATABASES = {
    "default": env.db_url(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}
DATABASES["default"]["CONN_MAX_AGE"] = 0



# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# CORS_ALLOWED_ORIGINS = [
#     "http://localhost:3000",  # React app running on localhost

# ]

# For development purposes, you can use:
CORS_ALLOW_ALL_ORIGINS = env.bool('CORS_ALLOW_ALL_ORIGINS', default=DEBUG)
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[])
if DEBUG:
    CORS_ALLOWED_ORIGINS = list(dict.fromkeys([
        *CORS_ALLOWED_ORIGINS,
        'http://localhost:3000',
        'http://127.0.0.1:3000',
    ]))
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=["https://*.vercel.app"])


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "chatbot": "20/minute",
        "flight_booking": "5/minute",
        "flight_locations": "30/minute",
        "flight_search": "10/minute",
        "hotel_booking": "5/minute",
        "hotel_locations": "30/minute",
        "hotel_search": "10/minute",
    },
    "NUM_PROXIES": DRF_NUM_PROXIES,
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
