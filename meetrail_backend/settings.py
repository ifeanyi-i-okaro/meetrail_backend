"""
Django settings for meetrail_backend project.
"""

from pathlib import Path
from datetime import timedelta

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional in dev if not installed yet
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent.parent
import os
if load_dotenv:
    load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------
# ✅ GIS LIB PATHS (optional, for GeoDjango)
# ---------------------------------------------------------------------
GDAL_LIBRARY_PATH = os.getenv("GDAL_LIBRARY_PATH")
GEOS_LIBRARY_PATH = os.getenv("GEOS_LIBRARY_PATH")
PROJ_LIB = os.getenv("PROJ_LIB")

if GDAL_LIBRARY_PATH:
    os.environ["GDAL_LIBRARY_PATH"] = GDAL_LIBRARY_PATH
if GEOS_LIBRARY_PATH:
    os.environ["GEOS_LIBRARY_PATH"] = GEOS_LIBRARY_PATH
if PROJ_LIB:
    os.environ["PROJ_LIB"] = PROJ_LIB
SECRET_KEY = "django-insecure-$6n9(%j38ojx5)cx#fu)2g50^_hu0wobhx5qf(ltj)716-v%1d"
DEBUG = True
ALLOWED_HOSTS = ["*"]

# ---------------------------------------------------------------------
# ✅ INSTALLED APPS
# ---------------------------------------------------------------------
INSTALLED_APPS = [
    # Django core
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",

    # Local
    "channels",
    "accounts",
    "trailbook",
]

# Enable GeoDjango only when GDAL/GEOS are installed locally.
if os.getenv("ENABLE_GIS", "0") == "1":
    INSTALLED_APPS.append("django.contrib.gis")

# ---------------------------------------------------------------------
# ✅ MIDDLEWARE
# ---------------------------------------------------------------------
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",       # 👈 Must be at the top
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    # Disable CSRF globally for API endpoints (or control with decorator)
    "django.middleware.csrf.CsrfViewMiddleware",  
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


ASGI_APPLICATION = "meetrail_backend.asgi.application"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [("127.0.0.1", 6379)],
        },
    },
}

# ---------------------------------------------------------------------
# ✅ CORS SETTINGS
# ---------------------------------------------------------------------
CORS_ALLOW_ALL_ORIGINS = True  # 👈 For testing (use specific origins in prod)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = ["*"]
CORS_ALLOW_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]

# ---------------------------------------------------------------------
# ✅ AUTH MODEL
# ---------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

# ---------------------------------------------------------------------
# ✅ REST FRAMEWORK CONFIG
# ---------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
}

# ---------------------------------------------------------------------
# ✅ JWT SETTINGS (Optional but good to define)
# ---------------------------------------------------------------------
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# ---------------------------------------------------------------------
# ✅ DATABASE
# ---------------------------------------------------------------------
DB_ENGINE = os.getenv("DB_ENGINE", "sqlite").lower()

if DB_ENGINE in {"postgis", "postgres", "postgresql"}:
    DATABASES = {
        "default": {
            "ENGINE": "django.contrib.gis.db.backends.postgis",
            "NAME": os.getenv("DB_NAME", "meetrail"),
            "USER": os.getenv("DB_USER", "postgres"),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ---------------------------------------------------------------------
# ✅ TEMPLATES / URLS / STATIC
# ---------------------------------------------------------------------
ROOT_URLCONF = "meetrail_backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

WSGI_APPLICATION = "meetrail_backend.wsgi.application"

STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

TRAILBOOK_PLAYBACK_AUTORUN = os.getenv("TRAILBOOK_PLAYBACK_AUTORUN", "1") == "1"
TRAILBOOK_PLAYBACK_FPS = int(os.getenv("TRAILBOOK_PLAYBACK_FPS", "8"))
TRAILBOOK_PLAYBACK_MAX_SECONDS = int(os.getenv("TRAILBOOK_PLAYBACK_MAX_SECONDS", "900"))
TRAILBOOK_PLAYBACK_MAX_FRAMES = int(os.getenv("TRAILBOOK_PLAYBACK_MAX_FRAMES", "7200"))
TRAILBOOK_PLAYBACK_MOMENT_FLASH_SECONDS = float(
    os.getenv("TRAILBOOK_PLAYBACK_MOMENT_FLASH_SECONDS", "3.5")
)
TRAILBOOK_PLAYBACK_VIDEO_MAX_SECONDS = float(
    os.getenv("TRAILBOOK_PLAYBACK_VIDEO_MAX_SECONDS", "8.0")
)
TRAILBOOK_MAP_TILE_URL_TEMPLATE = os.getenv(
    "TRAILBOOK_MAP_TILE_URL_TEMPLATE",
    "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
)
TRAILBOOK_MAP_TILE_USER_AGENT = os.getenv(
    "TRAILBOOK_MAP_TILE_USER_AGENT",
    "Meetrail/1.0 (+https://meetrail.app)",
)
TRAILBOOK_MAP_TILE_TIMEOUT_SECONDS = float(
    os.getenv("TRAILBOOK_MAP_TILE_TIMEOUT_SECONDS", "3.0")
)

# TrailBook media uploads (video/photo moments)
DATA_UPLOAD_MAX_MEMORY_SIZE = int(
    os.getenv("DATA_UPLOAD_MAX_MEMORY_SIZE", str(100 * 1024 * 1024))
)
FILE_UPLOAD_MAX_MEMORY_SIZE = int(
    os.getenv("FILE_UPLOAD_MAX_MEMORY_SIZE", str(20 * 1024 * 1024))
)

# ---------------------------------------------------------------------
# ✅ TIME & LANGUAGE
# ---------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True




DEFAULT_FROM_EMAIL = 'MeeTrail <info@geodatapals.com>'

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_USE_SSL = True
EMAIL_USE_TLS = False
EMAIL_HOST = 'mail.privateemail.com'
EMAIL_HOST_USER = 'info@geodatapals.com'
EMAIL_HOST_PASSWORD = 'Wasgenstrasse1'
EMAIL_PORT = 465
