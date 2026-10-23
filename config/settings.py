"""Settings for CareSlot. Everything that differs between environments comes from env vars."""

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG")
# The fallback key is only for local development and tests; render.yaml generates a real one.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-local-development-key")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
if render_host := os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(render_host)
CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS if host not in {"localhost", "127.0.0.1"}]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "scheduling",
]

MIDDLEWARE = [
    # First, so platform health probes are answered before ALLOWED_HOSTS validation.
    "scheduling.middleware.HealthCheckMiddleware",
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
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

# MySQL 8 everywhere. The default matches docker-compose.yml (host port 3307, so it doesn't clash
# with an existing local MySQL/MariaDB on 3306). Production sets DATABASE_URL.
DATABASES = {
    "default": dj_database_url.config(
        default="mysql://careslot:careslot@127.0.0.1:3307/careslot",
        conn_max_age=60,
        conn_health_checks=True,
    )
}
if DATABASES["default"]["ENGINE"] == "django.db.backends.mysql":
    _options = DATABASES["default"].setdefault("OPTIONS", {})
    # Hosted MySQL URLs use "?ssl-mode=REQUIRED"; the mysqlclient driver expects "ssl_mode".
    if "ssl-mode" in _options:
        _options["ssl_mode"] = _options.pop("ssl-mode")
    _options.setdefault("charset", "utf8mb4")
    # Strict mode: reject over-long or invalid values instead of silently truncating them.
    _options.setdefault("init_command", "SET sql_mode='STRICT_TRANS_TABLES'")
    DATABASES["default"]["TEST"] = {"CHARSET": "utf8mb4", "COLLATION": "utf8mb4_unicode_ci"}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
# The clinic's local time zone. Datetimes are stored in UTC; working hours and naive input are
# interpreted in this zone, and API responses are rendered in it.
TIME_ZONE = os.environ.get("CLINIC_TIME_ZONE", "Africa/Nairobi")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Booking rules
SLOT_MINUTES = 30
BOOKING_MIN_NOTICE_MINUTES = int(os.environ.get("BOOKING_MIN_NOTICE_MINUTES", "60"))

REST_FRAMEWORK = {
    # No API authentication in this assessment scope; see README "Trade-offs".
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "scheduling.exceptions.api_exception_handler",
    "UNAUTHENTICATED_USER": None,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "CareSlot API",
    "DESCRIPTION": "Clinic appointment booking: doctor availability, booking, cancellation and rescheduling.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
