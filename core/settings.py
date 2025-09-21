# core/settings.py
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# =========================
# Segurança / Debug
# =========================
SECRET_KEY = os.getenv("SECRET_KEY", "troque-esta-chave")
DEBUG = os.getenv("DEBUG", "1") == "1"

# Em Docker, você acessa por 0.0.0.0:8000; mantenha localhost/127.0.0.1 também
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0").split(",")

# Necessário para POST/CSRF no Docker/Nginx (ajuste se usar domínio)
CSRF_TRUSTED_ORIGINS = os.getenv(
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000"
).split(",")

# Redirecionamentos de auth
LOGIN_URL = os.getenv("LOGIN_URL", "login")
LOGIN_REDIRECT_URL = os.getenv("LOGIN_REDIRECT_URL", "painel:dashboard")
LOGOUT_REDIRECT_URL = os.getenv("LOGOUT_REDIRECT_URL", "login")

# =========================
# Apps
# =========================
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",

    # seus apps
    "widget_tweaks",
    "rest_framework",
    "clientes",
    "solicitacoes",
    "painel",
    "agendamentos",
    "servicos",
    "barbearias",

    # WhiteNoise não precisa app; é só middleware/opcional
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",

    # --- WhiteNoise (opcional, recomendado em produção sem Nginx) ---
    # Ative se adicionou 'whitenoise' no requirements.txt
    # "whitenoise.middleware.WhiteNoiseMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # certifica que o Django acha seus templates raiz (ex: templates/registration/login.html)
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

WSGI_APPLICATION = "core.wsgi.application"

# =========================
# Banco de Dados (Docker-ready)
# =========================


def _env(*keys, default=None):
    # retorna o primeiro env existente
    for k in keys:
        v = os.getenv(k)
        if v not in (None, ""):
            return v
    return default

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _env("POSTGRES_DB", "DB_NAME", default="django_db"),
        "USER": _env("POSTGRES_USER", "DB_USER", default="django"),
        "PASSWORD": _env("POSTGRES_PASSWORD", "DB_PASSWORD", default="secret"),
        "HOST": _env("POSTGRES_HOST", "DB_HOST", default="db"),
        "PORT": _env("POSTGRES_PORT", "DB_PORT", default="5432"),
    }
}

# =========================
# Senhas
# =========================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# =========================
# i18n / L10n (Brasil)
# =========================
LANGUAGE_CODE = os.getenv("LANGUAGE_CODE", "pt-br")
TIME_ZONE = os.getenv("TIME_ZONE", "America/Sao_Paulo")
USE_I18N = True
USE_TZ = True

# =========================
# Arquivos estáticos
# =========================
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"   # destino do collectstatic

# Somente a pasta global de origem:
STATICFILES_DIRS = [ BASE_DIR / "static" ]

# WhiteNoise (opcional): habilite se ativou o middleware
# STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# =========================
# REST Framework (opcional mínimo)
# =========================
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        # adicione BrowsableAPIRenderer em debug se quiser
    ] if not DEBUG else [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ]
}

# =========================
# Logging — útil no Docker
# =========================
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO" if not DEBUG else "DEBUG",
    },
}
