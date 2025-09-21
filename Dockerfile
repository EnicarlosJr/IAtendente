FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/home/appuser/.local/bin:$PATH"

WORKDIR /app

# --- Sistema ---
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      libpq-dev \
      netcat-traditional \
    && rm -rf /var/lib/apt/lists/*

# --- Python deps ---
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
 && pip install --no-cache-dir -r /app/requirements.txt

# --- setup.sh primeiro (com dono e permissão corretos) ---
#   Isso permite cachear e garante execução mesmo sem bind mount.
RUN useradd -m appuser
COPY --chown=appuser:appuser setup.sh /app/setup.sh
RUN sed -i 's/\r$//' /app/setup.sh && chmod 755 /app/setup.sh

# --- Código restante ---
COPY --chown=appuser:appuser . /app

USER appuser

EXPOSE 8000

# Importante: chame via /bin/sh para não depender do bit executável ao montar volume
ENTRYPOINT ["/bin/sh", "/app/setup.sh"]
