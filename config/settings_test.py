"""
Settings para tests (SQLite en memoria, sin servicios externos).
"""
from .settings import *  # noqa: F403, F401

DEBUG = True
SECRET_KEY = "test-not-for-production"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

KAFKA_BOOTSTRAP_SERVERS = "localhost:0"  # no se usa en tests básicos
