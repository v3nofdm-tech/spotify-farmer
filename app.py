"""
🎵 Spotify Farmer — app.py
Architecture :
  1. Flask server → OAuth one-time setup (visite l'URL une fois)
  2. librespot subprocess → apparaît comme "V3no Player" dans Spotify Connect
  3. Watchdog loop → vérifie que ça joue, relance si ça s'arrête
"""
import os
import sys
import time
import logging
import asyncio
import threading
import subprocess
import json
from pathlib import Path

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from flask import Flask, request, redirect

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
CLIENT_ID       = os.getenv("SPOTIFY_CLIENT_ID",     "a93f99b0286d4da6bb67021e1774489c")
CLIENT_SECRET   = os.getenv("SPOTIFY_CLIENT_SECRET", "e849fd278b2f46d9822ec6cebf70a0c9")
SPOTIFY_USER    = os.getenv("SPOTIFY_USERNAME",      "V3no")
SPOTIFY_PASS    = os.getenv("SPOTIFY_PASSWORD",      "")
DEVICE_NAME     = os.getenv("SPOTIFY_DEVICE_NAME",   "V3no Player")
ARTIST_ID       = os.getenv("SPOTIFY_ARTIST_ID",     "4tj9yRpZ3I6ymn8QnMLJhw")
RAILWAY_DOMAIN  = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")  # auto-injecté par Railway
PORT            = int(os.getenv("PORT", "8888"))

REDIRECT_URI    = f"https://{RAILWAY_DOMAIN}/callback" if RAILWAY_DOMAIN else f"http://localhost:{PORT}/callback"
TOKEN_CACHE     = "/tmp/.spotify_token_cache"

SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "streaming",
])

# ─── OAUTH ────────────────────────────────────────────────────────────────────
oauth = SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=SCOPES,
    cache_path=TOKEN_CACHE,
    open_browser=False,
)

app = Flask(__name__)
_setup_done = threading.Event()


@app.route("/")
def index():
    token_info = oauth.get_cached_token()
    if token_info:
        return "<h2>✅ Spotify Farmer actif ! Retourne sur Telegram.</h2>"
    auth_url = oauth.get_authorize_url()
    return (
        f"<h2>🎵 Setup Spotify Farmer</h2>"
        f"<p>Clique le bouton ci-dessous pour autoriser :</p>"
        f'<a href="{auth_url}" style="font-size:20px;padding:12px 24px;background:#1DB954;'
        f'color:white;text-decoration:none;border-radius:25px;">✅ Autoriser Spotify</a>'
    )


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "❌ Erreur — pas de code reçu", 400
    token_info = oauth.get_access_token(code, as_dict=True)
    if token_info:
        log.info("[Setup] ✅ Token Spotify obtenu et sauvegardé !")
        _setup_done.set()
        return "<h2>✅ Autorisé ! Le farmer démarre...</h2><p>Tu peux fermer cette page.</p>"
    return "❌ Erreur lors de l'obtention du token", 400


# ─── LIBRESPOT ────────────────────────────────────────────────────────────────

def start_librespot() -> subprocess.Popen:
    """Lance librespot en background — apparaît comme device Spotify."""
    cmd = [
        "librespot",
        "--name",     DEVICE_NAME,
        "--username", SPOTIFY_USER,
        "--password", SPOTIFY_PASS,
        "--backend",  "pipe",           # pas de sortie audio réelle
        "--bitrate",  "320",            # qualité max pour le Wrapped
        "--quiet",
    ]
    log.info(f"[librespot] 🎵 Démarrage du device '{DEVICE_NAME}'...")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    log.info(f"[librespot] ✅ Device actif (PID {proc.pid})")
    return proc


# ─── WATCHDOG ─────────────────────────────────────────────────────────────────

def get_spotify_client() -> spotipy.Spotify:
    token_info = oauth.get_cached_token()
    if not token_info:
        raise RuntimeError("Pas de token — setup OAuth d'abord")
    if oauth.is_token_expired(token_info):
        token_info = oauth.refresh_access_token(token_info["refresh_token"])
    return spotipy.Spotify(auth=token_info["access_token"])


def get_device_id(sp: spotipy.Spotify) -> str | None:
    """Trouve le device_id de 'V3no Player'."""
    devices = sp.devices()
    for d in devices.get("devices", []):
        if d["name"] == DEVICE_NAME:
            return d["id"]
    return None


def get_artist_tracks(sp: spotipy.Spotify) -> list[str]:
    """Récupère tous les URIs des tracks de l'artiste."""
    tracks = []
    # Albums de l'artiste
    albums = sp.artist_albums(f"spotify:artist:{ARTIST_ID}", album_type="album,single", limit=50)
    for album in albums.get("items", []):
        album_tracks = sp.album_tracks(album["id"], limit=50)
        for t in album_tracks.get("items", []):
            tracks.append(t["uri"])
    log.info(f"[Watchdog] 📀 {len(tracks)} tracks trouvées pour l'artiste")
    return tracks


def watchdog_loop():
    """
    Boucle principale :
    - Toutes les 30s vérifie si ça joue sur V3no Player
    - Si arrêté → relance la playlist de l'artiste en shuffle
    """
    import random

    log.info("[Watchdog] ⌚ Démarrage watchdog — attend le token OAuth...")
    _setup_done.wait()  # Attend que l'OAuth soit fait
    log.info("[Watchdog] ✅ Token dispo — surveillance active !")

    tracks      = []
    device_id   = None
    retry_count = 0

    while True:
        try:
            sp = get_spotify_client()

            # Récupère les tracks au premier lancement ou si vide
            if not tracks:
                tracks = get_artist_tracks(sp)
                if not tracks:
                    log.warning("[Watchdog] ⚠️ Aucune track trouvée — retry dans 60s")
                    time.sleep(60)
                    continue

            # Trouve le device
            if not device_id:
                device_id = get_device_id(sp)
                if not device_id:
                    log.warning(f"[Watchdog] 💤 Device '{DEVICE_NAME}' pas encore visible — retry dans 15s")
                    time.sleep(15)
                    continue
                log.info(f"[Watchdog] 🎯 Device trouvé : {device_id}")

            # Vérifie l'état de lecture
            playback = sp.current_playback()

            is_playing = (
                playback is not None
                and playback.get("is_playing")
                and playback.get("device", {}).get("name") == DEVICE_NAME
            )

            if not is_playing:
                log.info("[Watchdog] ▶️ Pas en lecture — lancement shuffle artiste !")
                shuffled = random.sample(tracks, min(len(tracks), 50))
                sp.start_playback(
                    device_id=device_id,
                    uris=shuffled,
                )
                sp.shuffle(True, device_id=device_id)
                sp.repeat("context", device_id=device_id)
                retry_count = 0
                log.info("[Watchdog] 🎵 Lecture lancée en shuffle !")
            else:
                current = playback.get("item", {}).get("name", "?")
                log.debug(f"[Watchdog] ✅ En lecture : {current}")

        except Exception as e:
            retry_count += 1
            log.error(f"[Watchdog] ❌ Erreur (#{retry_count}): {e}")
            if retry_count > 5:
                device_id = None  # Force re-détection du device
                retry_count = 0

        time.sleep(30)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 55)
    log.info("🎵 SPOTIFY FARMER — Starting up...")
    log.info(f"   Device     : {DEVICE_NAME}")
    log.info(f"   Artist ID  : {ARTIST_ID}")
    log.info(f"   Redirect   : {REDIRECT_URI}")
    log.info("=" * 55)

    # Check si token déjà en cache (redeploy → pas besoin de re-autoriser)
    if oauth.get_cached_token():
        log.info("[Main] ✅ Token en cache — setup déjà fait !")
        _setup_done.set()
    else:
        log.info(f"[Main] 🔐 Setup OAuth requis → visite : https://{RAILWAY_DOMAIN or f'localhost:{PORT}'}")

    # Lance librespot en background
    librespot_proc = start_librespot()

    # Lance le watchdog dans un thread séparé
    watchdog_thread = threading.Thread(target=watchdog_loop, daemon=True)
    watchdog_thread.start()

    # Flask en foreground (pour OAuth + healthcheck Railway)
    app.run(host="0.0.0.0", port=PORT, debug=False)


if __name__ == "__main__":
    main()
