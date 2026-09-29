"""
Django settings for the Sprint 2 GUI.

No database is configured: Section 25 (Scope boundaries) rules out database
persistence, and the app's real state is app.session.Session, held in
gui/session_store.py (see that module's docstring). Django's session
framework still needs a way to give one browser a stable key between
requests -- SESSION_ENGINE is set to signed_cookies below so that needs no
database, no migrations, and no sqlite3 file.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "django-insecure-change-me-before-any-real-deployment"

DEBUG = True

ALLOWED_HOSTS: list[str] = ["*"]  # course project, no production deployment (Section 25)

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "django.contrib.sessions",
    "gui",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# No database: see module docstring. Nothing in INSTALLED_APPS needs
# migrations (no admin/auth/contenttypes), so this is intentionally empty.
DATABASES = {}

SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
