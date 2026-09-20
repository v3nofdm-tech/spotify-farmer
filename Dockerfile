# syntax=docker/dockerfile:1
# ── Étape 1 : Compilation de librespot (Rust) depuis la source ──
FROM rust:1.76-slim-bookworm AS builder
RUN apt-get update && apt-get install -y pkg-config libasound2-dev build-essential
# On compile la version master de GitHub pour avoir les derniers fix de login Spotify
RUN cargo install --git https://github.com/librespot-org/librespot.git librespot

# ── Étape 2 : Image finale légère ──
FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y libasound2 curl && rm -rf /var/lib/apt/lists/*

# Copie du binaire fraîchement compilé
COPY --from=builder /usr/local/cargo/bin/librespot /usr/local/bin/librespot

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8888
CMD ["python", "app.py"]
