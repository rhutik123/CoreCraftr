"""
Django settings for CoreCraftr (corecraftr package — Computer Hardware E-Commerce & Intelligent PC Builder).

All sensitive credentials and environment-specific settings are loaded from
environment variables (and an optional local .env file). Never commit real
secrets to version control.
"""

import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - fallback if python-dotenv is absent
    load_dotenv = None

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

if load_dotenv is not None:
    env_path = BASE_DIR / '.env'
    if env_path.exists():
        load_dotenv(env_path)


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_list(name: str, default: list[str] | None = None) -> list[str]:
    val = os.environ.get(name)
    if not val:
        return default or []
    return [item.strip() for item in val.split(',') if item.strip()]


# SECURITY WARNING: keep the secret key used in production secret!
DEBUG = _env_bool('DJANGO_DEBUG', default=True)

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '').strip()
if not SECRET_KEY or SECRET_KEY.startswith('replace-with-'):
    if DEBUG:
        # Development-only ephemeral fallback; never use in production.
        SECRET_KEY = 'dev-only-insecure-key-change-via-DJANGO_SECRET_KEY-in-env'
    else:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is False.')

ALLOWED_HOSTS = _env_list('DJANGO_ALLOWED_HOSTS', ['127.0.0.1', 'localhost'] if DEBUG else [])
CSRF_TRUSTED_ORIGINS = _env_list(
    'DJANGO_CSRF_TRUSTED_ORIGINS',
    ['http://127.0.0.1:8000', 'http://localhost:8000'] if DEBUG else [],
)


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party apps
    'rest_framework',
    'django_filters',
    # Local modular monolith apps
    'store.apps.StoreConfig',
    'pc_builder.apps.PcBuilderConfig',
    'ai_engine.apps.AiEngineConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'corecraftr.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'store.context_processors.global_store_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'corecraftr.wsgi.application'
ASGI_APPLICATION = 'corecraftr.asgi.application'


# Database configuration
# Primary target: PostgreSQL configured via environment variables.
# Graceful local fallback: SQLite when DB_ENGINE=sqlite or when PostgreSQL
# password is not provided in development/test environments.

DB_ENGINE = os.environ.get('DB_ENGINE', 'postgresql').strip().lower()
DB_NAME = os.environ.get('DB_NAME', 'corecraftr_db').strip()
DB_USER = os.environ.get('DB_USER', 'postgres').strip()
DB_PASSWORD = os.environ.get('DB_PASSWORD', '').strip()
DB_HOST = os.environ.get('DB_HOST', '127.0.0.1').strip()
DB_PORT = os.environ.get('DB_PORT', '5432').strip()
ALLOW_SQLITE_FALLBACK = _env_bool('DJANGO_ALLOW_SQLITE_FALLBACK', default=True)

_has_pg_password = bool(DB_PASSWORD) and not DB_PASSWORD.startswith('replace-with-')

if DB_ENGINE in ('postgresql', 'postgres') and (_has_pg_password or not ALLOW_SQLITE_FALLBACK):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': DB_NAME,
            'USER': DB_USER,
            'PASSWORD': DB_PASSWORD,
            'HOST': DB_HOST,
            'PORT': DB_PORT,
            'CONN_MAX_AGE': 60,
        }
    }
    DATABASE_MODE = 'postgresql'
else:
    SQLITE_NAME = os.environ.get('SQLITE_DB_PATH', str(BASE_DIR / 'db.sqlite3'))
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': SQLITE_NAME,
        }
    }
    DATABASE_MODE = 'sqlite_fallback'


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.environ.get('DJANGO_TIME_ZONE', 'Asia/Kolkata')
USE_I18N = True
USE_TZ = True


# Static files & Media files
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'
        if not DEBUG
        else 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# Authentication URLs
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'home'


# Email configuration (never hardcode credentials)
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = _env_bool('EMAIL_USE_TLS', default=True)
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@corecraftr.local')


# Security Hardening
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True

if not DEBUG:
    SECURE_SSL_REDIRECT = _env_bool('SECURE_SSL_REDIRECT', default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True


# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
}


# AI Integration Configuration (optional; deterministic fallback used if unconfigured)
AI_PROVIDER = os.environ.get('AI_PROVIDER', 'none').strip().lower()
AI_API_KEY = os.environ.get('AI_API_KEY', '').strip()
if AI_API_KEY.startswith('replace-with-'):
    AI_API_KEY = ''
AI_MODEL = os.environ.get('AI_MODEL', 'gpt-4o-mini').strip()
AI_TIMEOUT_SECONDS = int(os.environ.get('AI_TIMEOUT_SECONDS', '15'))

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
