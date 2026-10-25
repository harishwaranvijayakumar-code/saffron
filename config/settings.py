
import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# -------------------------------------------------------------------
# Core security and environment
# -------------------------------------------------------------------

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be configured in the environment."
    )

DEBUG = os.getenv("DJANGO_DEBUG", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv(
        "DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost"
    ).split(",")
    if host.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

# Only enable proxy SSL detection when the hosting platform's proxy
# is trusted and configured to set this header correctly.
if os.getenv("DJANGO_USE_X_FORWARDED_PROTO", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_SSL_REDIRECT = (
    not DEBUG
    and os.getenv("DJANGO_SECURE_SSL_REDIRECT", "true").strip().lower()
    in {"1", "true", "yes"}
)

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# Enable HSTS only after HTTPS is confirmed to work for the entire
# deployment and any subdomains covered by the policy.
SECURE_HSTS_SECONDS = int(
    os.getenv("DJANGO_SECURE_HSTS_SECONDS", "0")
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = (
    os.getenv("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", "false")
    .strip()
    .lower()
    in {"1", "true", "yes"}
)
SECURE_HSTS_PRELOAD = (
    os.getenv("DJANGO_SECURE_HSTS_PRELOAD", "false")
    .strip()
    .lower()
    in {"1", "true", "yes"}
)

# -------------------------------------------------------------------
# Database
# -------------------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise ImproperlyConfigured(
        "DATABASE_URL must be configured in the environment."
    )

DATABASES = {
    "default": dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=60,
        conn_health_checks=True,
    )
}

# Set DATABASE_SSL_REQUIRE=true for a database provider that supports
# PostgreSQL TLS and requires sslmode=require.
if os.getenv("DATABASE_SSL_REQUIRE", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}:
    DATABASES["default"].setdefault("OPTIONS", {})["sslmode"] = "require"

# -------------------------------------------------------------------
# Django applications
# -------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "runs",
]

# -------------------------------------------------------------------
# Middleware
# -------------------------------------------------------------------

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

# -------------------------------------------------------------------
# Templates
# -------------------------------------------------------------------

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# -------------------------------------------------------------------
# Internationalization
# -------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# -------------------------------------------------------------------
# Static files
# -------------------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}

# -------------------------------------------------------------------
# Authentication and application defaults
# -------------------------------------------------------------------

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/runs/"
LOGOUT_REDIRECT_URL = "/accounts/login/"
