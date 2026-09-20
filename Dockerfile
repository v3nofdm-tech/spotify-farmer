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

# ── spotifyd binary (Spotify daemon basé sur librespot, avec vrais binaires) ─
ARG SPOTIFYD_VERSION=v0.3.5
RUN curl -fsSL \
    "https://github.com/Spotifyd/spotifyd/releases/download/${SPOTIFYD_VERSION}/spotifyd-linux-x86_64-slim.tar.gz" \
    -o /tmp/spotifyd.tar.gz \
    && tar -xzf /tmp/spotifyd.tar.gz -C /usr/local/bin/ \
    && chmod +x /usr/local/bin/spotifyd \
    && rm /tmp/spotifyd.tar.gz

WORKDIR /app

# ── Python deps ───────────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY . .

EXPOSE 8888

CMD ["python3", "app.py"]
