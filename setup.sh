#!/bin/sh
set -e

log() { printf "\033[1;34m[setup]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[setup]\033[0m %s\n" "$*"; }
err() { printf "\033[1;31m[setup]\033[0m %s\n" "$*"; }

DB_HOST="${POSTGRES_HOST:-${DB_HOST:-db}}"
DB_PORT="${POSTGRES_PORT:-${DB_PORT:-5432}}"

echo "⏳ Aguardando Postgres em ${DB_HOST}:${DB_PORT}..."
until nc -z "$DB_HOST" "$DB_PORT"; do
  echo "Ainda não está pronto..."
  sleep 2
done
echo "✅ Postgres ok!"

# ============= Espera pelo Postgres =============
log "Aguardando Postgres em ${DB_HOST}:${DB_PORT}..."
ATTEMPTS=0
MAX_ATTEMPTS=60   # ~2 min (60 * 2s)
until nc -z "${DB_HOST}" "${DB_PORT}"; do
  ATTEMPTS=$((ATTEMPTS+1))
  if [ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]; then
    err "Timeout ao aguardar Postgres em ${DB_HOST}:${DB_PORT}."
    exit 1
  fi
  sleep 2
done
log "Postgres disponível! ✅"

# ============= Dependências Python =============
if [ -f "requirements.txt" ]; then
  log "Instalando dependências (requirements.txt)..."
  pip install --no-cache-dir -r requirements.txt
else
  warn "Arquivo requirements.txt não encontrado — pulando instalação de deps."
fi

# ============= Migrações =============
log "Aplicando migrações..."
python manage.py makemigrations --noinput || true
python manage.py migrate --noinput

# ============= Coleta de estáticos =============
# casa com seu settings: STATIC_ROOT = BASE_DIR / "staticfiles"
STATIC_ROOT_DIR="/app/staticfiles"
mkdir -p "$STATIC_ROOT_DIR" || true
chmod -R 775 "$STATIC_ROOT_DIR" 2>/dev/null || true

log "Coletando arquivos estáticos..."
python manage.py collectstatic --noinput || true

# ============= Superusuário idempotente (com django.setup) =============
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_EMAIL" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
  log "Garantindo superusuário '${DJANGO_SUPERUSER_USERNAME}'..."
  python - <<'PY' || warn "Falha ao garantir superusuário (continuando start)."
import os
import django

# Use DJANGO_SETTINGS_MODULE se já veio do ambiente; senão, assuma 'core.settings'
os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.getenv("DJANGO_SETTINGS_MODULE", "core.settings"))
django.setup()

from django.contrib.auth import get_user_model

username = os.environ["DJANGO_SUPERUSER_USERNAME"]
email = os.environ["DJANGO_SUPERUSER_EMAIL"]
password = os.environ["DJANGO_SUPERUSER_PASSWORD"]

User = get_user_model()
u, created = User.objects.get_or_create(
    username=username,
    defaults={"email": email, "is_staff": True, "is_superuser": True},
)
if created:
    u.set_password(password)
    u.save()
    print("[setup] Superusuário criado.")
else:
    changed = False
    if u.email != email:
        u.email = email; changed = True
    if not u.is_staff:
        u.is_staff = True; changed = True
    if not u.is_superuser:
        u.is_superuser = True; changed = True
    if changed:
        u.save(); print("[setup] Superusuário existente ajustado.")
    else:
        print("[setup] Superusuário já existia, ok.")
PY
else
  warn "Variáveis de superusuário ausentes — pulando criação automática."
  warn "Defina: DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_EMAIL, DJANGO_SUPERUSER_PASSWORD"
fi

# ============= Tailwind: verificação/compilação (opcional) =============
if python manage.py help tailwind >/dev/null 2>&1; then
  log "Detectado django-tailwind. Rodando build..."
  python manage.py tailwind build || warn "Falha ao rodar 'manage.py tailwind build' (verifique configuração do django-tailwind)."
elif command -v npm >/dev/null 2>&1 && [ -f "package.json" ]; then
  log "Detectado package.json e npm. Rodando build do Tailwind..."
  if [ -f "package-lock.json" ]; then npm ci || npm install; else npm install; fi
  if npm run | grep -qE 'build|tw:build'; then
    npm run build 2>/dev/null || npm run tw:build 2>/dev/null || warn "Nenhum script 'build'/'tw:build' executou."
  else
    warn "Nenhum script de build definido no package.json."
  fi
else
  warn "Tailwind não detectado (django-tailwind ou npm/package.json). Pulando etapa de Tailwind."
fi

# ============= Start da aplicação =============
log "Iniciando comando final: $*"
exec "$@"
