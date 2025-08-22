from pathlib import Path
import os
import environ

# Initialize environment variables
env = environ.Env(
    # Set casting and default values
    DEBUG=(bool, False)
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
DEBUG = True

ALLOWED_HOSTS = ["*"]


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "base.apps.BaseConfig",
    "demo.apps.DemoConfig",
    'corsheaders',
    'rest_framework',
    "rest_framework.authtoken",
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    "django.middleware.security.SecurityMiddleware",
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


# Amadeus Api
CLIENT_ID = "LNCgkGOS2gsex21xG1RnpllQGaHwodig"
CLIENT_SECRET = "Z5KRodc373AzGjGw"


# Email configuration — prefer environment values and Brevo (Sendinblue) SMTP by default.
# Optional: set BREVO_API_KEY if you want to send via Brevo REST API instead of SMTP.
EMAIL_SERVICE = env('EMAIL_SERVICE', default='sendinblue').lower()
BREVO_API_KEY = env('BREVO_API_KEY', default='')  # xkeysib-... (optional, for REST)

if EMAIL_SERVICE == 'sendinblue' or EMAIL_SERVICE == 'brevo':
    # Brevo / Sendinblue SMTP
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = env('EMAIL_HOST', default='smtp-relay.brevo.com')
    EMAIL_PORT = env('EMAIL_PORT', default=587)
    # For many Brevo accounts use 'apikey' as the SMTP user; otherwise set the provided SMTP user
    EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='apikey')
    EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')  # xsmtpsib-...
    EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', True)

elif EMAIL_SERVICE == 'ses':
    # keep SES option if you still want it
    EMAIL_BACKEND = 'django_ses.SESBackend'
    EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
else:
    # fallback to console during development if misconfigured
    EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}



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
CORS_ALLOW_ALL_ORIGINS = True


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

STATIC_URL = "static/"

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
