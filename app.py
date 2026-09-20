"""
🎵 Spotify Farmer — app.py
Architecture :
  1. librespot (Python) → device Spotify Connect "V3no Player"
  2. Flask → OAuth one-time setup
  3. Watchdog → joue l'artiste en shuffle 24/7
"""
import os
import sys
import time
import logging
import threading
import random
from pathlib import Path

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from flask import Flask, request

# librespot Python
from librespot.core import Session
from librespot.audio.decoders import AudioQuality

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
CLIENT_ID      = os.getenv("SPOTIFY_CLIENT_ID",     "a93f99b0286d4da6bb67021e1774489c")
CLIENT_SECRET  = os.getenv("SPOTIFY_CLIENT_SECRET", "e849fd278b2f46d9822ec6cebf70a0c9")
SPOTIFY_USER   = os.getenv("SPOTIFY_USERNAME",      "v3kee2@proton.me")
SPOTIFY_PASS   = os.getenv("SPOTIFY_PASSWORD",      "")
DEVICE_NAME    = os.getenv("SPOTIFY_DEVICE_NAME",   "V3no Player")
ARTIST_ID      = os.getenv("SPOTIFY_ARTIST_ID",     "4tj9yRpZ3I6ymn8QnMLJhw")
RAILWAY_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
PORT           = int(os.getenv("PORT", "8888"))

REDIRECT_URI = (
    f"https://{RAILWAY_DOMAIN}/callback"
    if RAILWAY_DOMAIN
    else f"http://localhost:{PORT}/callback"
)
TOKEN_CACHE = "/tmp/.spotify_token_cache"

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
    if oauth.get_cached_token():
        return "<h2>✅ Spotify Farmer actif !</h2><p>Ferme cette page.</p>"
    auth_url = oauth.get_authorize_url()
    return (
        "<h2>🎵 Setup Spotify Farmer</h2>"
        "<p>Clique pour autoriser :</p>"
        f'<a href="{auth_url}" style="font-size:20px;padding:12px 24px;'
        f'background:#1DB954;color:white;text-decoration:none;border-radius:25px;">'
        f'✅ Autoriser Spotify</a>'
    )


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "❌ Pas de code", 400
    token_info = oauth.get_access_token(code, as_dict=True)
    if token_info:
        log.info("[OAuth] ✅ Token obtenu !")
        _setup_done.set()
        return "<h2>✅ Autorisé ! Le farmer démarre.</h2>"
    return "❌ Erreur token", 400


# ─── LIBRESPOT DEVICE ─────────────────────────────────────────────────────────

def start_librespot_device():
    """
    Crée un device Spotify Connect via librespot-python.
    Retry automatique toutes les 30s si ça fail.
    """
    retry = 0
    while True:
        try:
            log.info(f"[librespot] 🎵 Connexion à Spotify (tentative {retry + 1})...")
            conf = (
                Session.Configuration.Builder()
                .set_store_credentials(False)
                .build()
            )
            session = (
                Session.Builder(conf)
                .user_pass(SPOTIFY_USER, SPOTIFY_PASS)
                .create()
            )
            log.info(f"[librespot] ✅ Device '{DEVICE_NAME}' connecté !")
            retry = 0
            # Garde la session active
            while True:
                time.sleep(30)

        except Exception as e:
            retry += 1
            wait = min(retry * 15, 120)
            log.warning(f"[librespot] ⚠️ Erreur ({e}) — retry dans {wait}s")
            time.sleep(wait)


# ─── WATCHDOG ─────────────────────────────────────────────────────────────────

def get_sp() -> spotipy.Spotify:
    token_info = oauth.get_cached_token()
    if not token_info:
        raise RuntimeError("Pas de token OAuth")
    if oauth.is_token_expired(token_info):
        token_info = oauth.refresh_access_token(token_info["refresh_token"])
    return spotipy.Spotify(auth=token_info["access_token"])


def get_device_id(sp: spotipy.Spotify) -> str | None:
    for d in sp.devices().get("devices", []):
        if d["name"] == DEVICE_NAME:
            return d["id"]
    return None


def get_artist_tracks(sp: spotipy.Spotify) -> list[str]:
    tracks = []
    albums = sp.artist_albums(
        f"spotify:artist:{ARTIST_ID}",
        album_type="album,single",
        limit=50,
    )
    for album in albums.get("items", []):
        for t in sp.album_tracks(album["id"], limit=50).get("items", []):
            tracks.append(t["uri"])
    log.info(f"[Watchdog] 📀 {len(tracks)} tracks trouvées")
    return tracks


def watchdog_loop():
    log.info("[Watchdog] ⌚ Attend token OAuth...")
    _setup_done.wait()
    log.info("[Watchdog] ✅ Démarrage watchdog !")

    tracks    = []
    device_id = None
    retries   = 0

    while True:
        try:
            sp = get_sp()

            if not tracks:
                tracks = get_artist_tracks(sp)
                if not tracks:
                    time.sleep(60)
                    continue

            if not device_id:
                device_id = get_device_id(sp)
                if not device_id:
                    log.warning(f"[Watchdog] Device '{DEVICE_NAME}' pas encore visible...")
                    time.sleep(15)
                    continue
                log.info(f"[Watchdog] 🎯 Device trouvé : {device_id}")

            playback   = sp.current_playback()
            is_playing = (
                playback is not None
                and playback.get("is_playing")
                and playback.get("device", {}).get("name") == DEVICE_NAME
            )

            if not is_playing:
                shuffled = random.sample(tracks, min(len(tracks), 50))
                sp.start_playback(device_id=device_id, uris=shuffled)
                sp.shuffle(True, device_id=device_id)
                sp.repeat("context", device_id=device_id)
                log.info("[Watchdog] ▶️ Lecture lancée en shuffle !")
                retries = 0
            else:
                name = playback.get("item", {}).get("name", "?")
                log.debug(f"[Watchdog] ✅ En cours : {name}")

        except Exception as e:
            retries += 1
            log.error(f"[Watchdog] ❌ Erreur #{retries} : {e}")
            if retries > 5:
                device_id = None
                retries   = 0

        time.sleep(30)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 55)
    log.info("🎵 SPOTIFY FARMER v2 — Starting up...")
    log.info(f"   Device  : {DEVICE_NAME}")
    log.info(f"   Artist  : {ARTIST_ID}")
    log.info(f"   URL     : https://{RAILWAY_DOMAIN or f'localhost:{PORT}'}")
    log.info("=" * 55)

    # Token déjà en cache ?
    if oauth.get_cached_token():
        log.info("[Main] ✅ Token en cache — pas besoin de re-autoriser")
        _setup_done.set()
    else:
        log.info(f"[Main] 🔐 Visite : https://{RAILWAY_DOMAIN or f'localhost:{PORT}'}")

    # Lance librespot device en thread
    t_device = threading.Thread(target=start_librespot_device, daemon=True)
    t_device.start()

    # Lance watchdog en thread
    t_watchdog = threading.Thread(target=watchdog_loop, daemon=True)
    t_watchdog.start()

    # Flask en foreground
    app.run(host="0.0.0.0", port=PORT, debug=False)


if __name__ == "__main__":
    main()
