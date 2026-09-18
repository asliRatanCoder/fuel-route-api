"""
Django settings for the fuel-route-api project (Django 6.1).

Everything environment-specific is read from environment variables with
development-friendly defaults, so the project runs out of the box.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / 'data'


def env_bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() in {'1', 'true', 'yes', 'on'}


SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-dev-only-key-change-me-in-production',
)
DEBUG = env_bool('DJANGO_DEBUG', True)
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'routing',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Route plans and geocoding results are cached so that a repeated request (or
# the HTML map view of a plan that was just computed) never hits the external
# routing API again.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'fuel-route-api',
        'TIMEOUT': 60 * 60,
        'OPTIONS': {'MAX_ENTRIES': 500},
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'


REST_FRAMEWORK = {
    # Public, read-only API: no sessions/CSRF, JSON in and out.
    'DEFAULT_AUTHENTICATION_CLASSES': [],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'],
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_PARSER_CLASSES': ['rest_framework.parsers.JSONParser'],
    'UNAUTHENTICATED_USER': None,
    'EXCEPTION_HANDLER': 'routing.views.api_exception_handler',
}


# --- Fuel route planner -----------------------------------------------------

# Vehicle assumptions from the assignment.
VEHICLE_RANGE_MILES = 500.0
VEHICLE_MPG = 10.0

# A station counts as "on the route" when it lies within this many miles of
# the route line. Station coordinates are city-level, so this is deliberately
# a little generous.
ROUTE_CORRIDOR_MILES = float(os.environ.get('ROUTE_CORRIDOR_MILES', 10))

# The optimiser minimises fuel cost + this fixed cost per stop (the driver's
# time), which keeps it from planning many tiny top-ups to save a few cents.
# 0 gives the pure minimum fuel cost. Clients can override it per request.
FUEL_STOP_PENALTY_USD = float(os.environ.get('FUEL_STOP_PENALTY_USD', 5))

# Routing: any OSRM-compatible server (the public demo server needs no key).
OSRM_BASE_URL = os.environ.get('OSRM_BASE_URL', 'https://router.project-osrm.org')

# Geocoding fallback, only used when a location is neither "lat,lng" nor a
# "City, ST" found in the bundled gazetteer.
NOMINATIM_BASE_URL = os.environ.get('NOMINATIM_BASE_URL', 'https://nominatim.openstreetmap.org')

EXTERNAL_API_TIMEOUT = float(os.environ.get('EXTERNAL_API_TIMEOUT', 15))
EXTERNAL_API_USER_AGENT = os.environ.get(
    'EXTERNAL_API_USER_AGENT', 'fuel-route-api/1.0 (django coding assessment)'
)

# Maximum number of points in the route geometry returned to clients.
RESPONSE_GEOMETRY_MAX_POINTS = 2000


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'loggers': {'routing': {'handlers': ['console'], 'level': 'INFO'}},
}
