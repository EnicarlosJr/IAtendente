# core/settings.py
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")  # carrega variáveis do .env

# =========================
# Segurança / Debug
# =========================
SECRET_KEY = os.getenv("SECRET_KEY", "troque-esta-chave")
DEBUG = os.getenv("DEBUG", "1") == "1"

# Ajuste conforme seu ambiente (Docker, localhost etc.)
import socket
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "db")
if socket.gethostname() == "seu-host":  # rodando fora do docker
    POSTGRES_HOST = "127.0.0.1"

# Em Docker, você acessa por 0.0.0.0:8000; mantenha localhost/127.0.0.1 também
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0").split(",")

# Necessário para POST/CSRF no Docker/Nginx (ajuste se usar domínio)
CSRF_TRUSTED_ORIGINS = os.getenv(
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000"
).split(",")

# Redirecionamentos de auth
LOGIN_URL = "barb_auth:login"
LOGIN_REDIRECT_URL = "painel:dashboard"
LOGOUT_REDIRECT_URL = "barb_auth:login"

#Dias para o cliente ficar inativo
CLIENTE_INATIVO_DIAS = 90

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

    # Middleware para selecionar a barbearia atual (contexto multi-tenant)
    "barbearias.middleware.BarberShopMiddleware",
    "barbearias.middleware.ShopSlugMiddleware",

    # --- WhiteNoise (opcional, recomendado em produção sem Nginx) ---
    # Ative se adicionou 'whitenoise' no requirements.txt
    # "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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
                "barbearias.context_processors.shop_context",  # disponibiliza shop_slug em todos os templates
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


DB_ENGINE = os.getenv("DB_ENGINE", "sqlite")

if DB_ENGINE == "postgres":
    # ⚠️ Fora do Docker, o padrão deve ser 127.0.0.1
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", "django_db"),
            "USER": os.getenv("POSTGRES_USER", "django"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", "secret"),
            "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / os.getenv("DB_NAME", "db.sqlite3"),
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
