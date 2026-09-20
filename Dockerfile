# syntax=docker/dockerfile:1
FROM debian:bookworm-slim

LABEL description="Spotify 24/7 Farmer — librespot + watchdog"

# ── Dépendances système ────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y \
    curl \
    python3 \
    python3-pip \
    python3-venv \
    ca-certificates \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# ── librespot binary (client Spotify headless) ────────────────────────────────
# Télécharge le binaire pré-compilé depuis GitHub releases
ARG LIBRESPOT_VERSION=v0.6.0
RUN curl -fsSL \
    "https://github.com/librespot-org/librespot/releases/download/${LIBRESPOT_VERSION}/librespot-linux-x86_64.tar.gz" \
    -o /tmp/librespot.tar.gz \
    && tar -xzf /tmp/librespot.tar.gz -C /usr/local/bin/ \
    && chmod +x /usr/local/bin/librespot \
    && rm /tmp/librespot.tar.gz

WORKDIR /app

# ── Python deps ───────────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY . .

EXPOSE 8888

CMD ["python3", "app.py"]
