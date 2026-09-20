"""
🎵 Spotify Farmer v4 — The Ghost Setup
Compile et lance le VRAI binaire librespot en Rust.
Crée un device cloud 24/7 sans utiliser de tel ni de PC.
"""
import os
import time
import logging
import threading
import subprocess
import random
from flask import Flask, request

import spotipy
from spotipy.oauth2 import SpotifyOAuth

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
    if RAILWAY_DOMAIN else f"http://localhost:{PORT}/callback"
)
TOKEN_CACHE = "/tmp/.spotify_token_cache"

SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
])

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

# ─── FLASK OAUTH ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if oauth.get_cached_token():
        return "<h2>✅ Spotify Farmer actif !</h2><p>Le binaire cloud tourne 24/7 en fond.</p>"
    auth_url = oauth.get_authorize_url()
    return (
        "<h2>🎵 Setup Spotify Farmer (Ghost Mode)</h2>"
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
        return "<h2>✅ Autorisé !</h2><p>Le ghost device V3no Player prend le relais.</p>"
    return "❌ Erreur token", 400

# ─── GHOST DEVICE (LIBRESPOT RUST) ────────────────────────────────────────────

def start_ghost_device():
    """Lance le binaire librespot Rust en subprocess."""
    log.info(f"[Ghost] 🎵 Démarrage de librespot en tâche de fond...")
    cmd = [
        "librespot",
        "--name", DEVICE_NAME,
        "--username", SPOTIFY_USER,
        "--password", SPOTIFY_PASS,
        "--backend", "pipe",
        "--bitrate", "320",
        "--initial-volume", "100"
    ]
    
    while True:
        log.info(f"[Ghost] Lancement du process librespot...")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        
        # Lit les logs de librespot
        for line in proc.stderr:
            decoded = line.decode("utf-8", errors="replace").strip()
            if decoded:
                if "BadCredentials" in decoded:
                    log.error(f"[Ghost] ❌ Mauvais mot de passe ou compte bloqué par Spotify : {decoded}")
                else:
                    log.debug(f"[librespot] {decoded}")
        
        proc.wait()
        log.warning(f"[Ghost] ⚠️ Le process a crash (code {proc.returncode}), redémarrage dans 10s...")
        time.sleep(10)

# ─── WATCHDOG ─────────────────────────────────────────────────────────────────

def get_sp() -> spotipy.Spotify:
    token_info = oauth.get_cached_token()
    if not token_info:
        raise RuntimeError("Pas de token OAuth")
    if oauth.is_token_expired(token_info):
        token_info = oauth.refresh_access_token(token_info["refresh_token"])
    return spotipy.Spotify(auth=token_info["access_token"])

def get_artist_tracks(sp: spotipy.Spotify) -> list[str]:
    tracks = []
    albums = sp.artist_albums(f"spotify:artist:{ARTIST_ID}", album_type="album,single", limit=50)
    for album in albums.get("items", []):
        for t in sp.album_tracks(album["id"], limit=50).get("items", []):
            tracks.append(t["uri"])
    log.info(f"[Watchdog] 📀 {len(tracks)} tracks trouvées")
    return tracks

def watchdog_loop():
    log.info("[Watchdog] ⌚ Attend token OAuth...")
    _setup_done.wait()
    log.info("[Watchdog] ✅ Token OK — surveillance active !")

    tracks = []
    
    while True:
        try:
            sp = get_sp()

            if not tracks:
                tracks = get_artist_tracks(sp)
                if not tracks:
                    time.sleep(60)
                    continue

            # Cherche spécifiquement notre Ghost device
            devices = sp.devices().get("devices", [])
            ghost_id = next((d["id"] for d in devices if d["name"] == DEVICE_NAME), None)

            if not ghost_id:
                log.warning(f"[Watchdog] 💤 Le ghost device '{DEVICE_NAME}' n'est pas encore prêt, on attend...")
                time.sleep(15)
                continue

            playback = sp.current_playback()
            is_playing = (
                playback is not None
                and playback.get("is_playing")
                and playback.get("device", {}).get("name") == DEVICE_NAME
            )

            if not is_playing:
                shuffled = random.sample(tracks, min(len(tracks), 50))
                sp.start_playback(device_id=ghost_id, uris=shuffled)
                sp.shuffle(True, device_id=ghost_id)
                sp.repeat("context", device_id=ghost_id)
                log.info(f"[Watchdog] ▶️ Lecture forcée sur '{DEVICE_NAME}' (Fantôme) !")
            else:
                track = playback["item"]["name"]
                log.info(f"[Watchdog] ✅ En cours sur Fantôme : {track}")

        except Exception as e:
            log.error(f"[Watchdog] ❌ Erreur : {e}")

        time.sleep(30)

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 55)
    log.info("🎵 SPOTIFY FARMER v4 — Ghost Setup")
    log.info("=" * 55)

    if oauth.get_cached_token():
        _setup_done.set()

    threading.Thread(target=start_ghost_device, daemon=True).start()
    threading.Thread(target=watchdog_loop, daemon=True).start()

    app.run(host="0.0.0.0", port=PORT, debug=False)

if __name__ == "__main__":
    main()
