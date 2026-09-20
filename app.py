"""
🎵 Spotify Farmer v3 — Sans librespot
Le watchdog contrôle n'importe quel device actif sur le compte via Web API.
Ton tel avec Spotify en background = suffit, il joue 24/7.
"""
import os
import time
import logging
import threading
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
CLIENT_ID      = os.getenv("SPOTIFY_CLIENT_ID",    "a93f99b0286d4da6bb67021e1774489c")
CLIENT_SECRET  = os.getenv("SPOTIFY_CLIENT_SECRET","e849fd278b2f46d9822ec6cebf70a0c9")
ARTIST_ID      = os.getenv("SPOTIFY_ARTIST_ID",    "4tj9yRpZ3I6ymn8QnMLJhw")
RAILWAY_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN","")
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
        return (
            "<h2>✅ Spotify Farmer actif !</h2>"
            "<p>Le bot joue en boucle sur ton Spotify.</p>"
            "<p><a href='/status'>📊 Voir le statut</a></p>"
        )
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
        return (
            "<h2>✅ Autorisé !</h2>"
            "<p>Le farmer tourne maintenant 24/7 🎵</p>"
            "<p>Laisse Spotify ouvert sur ton tel en background — c'est tout !</p>"
        )
    return "❌ Erreur token", 400


@app.route("/status")
def status():
    try:
        sp  = get_sp()
        pb  = sp.current_playback()
        devs = sp.devices().get("devices", [])

        if pb and pb.get("is_playing"):
            track  = pb["item"]["name"]
            artist = pb["item"]["artists"][0]["name"]
            device = pb["device"]["name"]
            status_html = f"🔴 EN LECTURE<br><b>{track}</b> — {artist}<br>📱 {device}"
        else:
            status_html = "⏸️ En pause / Aucune lecture"

        dev_list = "<br>".join([f"📱 {d['name']} ({d['type']})" for d in devs]) or "Aucun device actif"
        return f"<h2>📊 Status</h2><p>{status_html}</p><h3>Devices disponibles :</h3><p>{dev_list}</p>"
    except Exception as e:
        return f"<p>Erreur : {e}</p>"


# ─── SPOTIFY CLIENT ───────────────────────────────────────────────────────────

def get_sp() -> spotipy.Spotify:
    token_info = oauth.get_cached_token()
    if not token_info:
        raise RuntimeError("Pas de token OAuth")
    if oauth.is_token_expired(token_info):
        token_info = oauth.refresh_access_token(token_info["refresh_token"])
    return spotipy.Spotify(auth=token_info["access_token"])


def get_any_device(sp: spotipy.Spotify) -> str | None:
    """Prend le premier device actif sur le compte."""
    devices = sp.devices().get("devices", [])
    if devices:
        # Préfère un device actif
        for d in devices:
            if d.get("is_active"):
                return d["id"]
        return devices[0]["id"]
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


# ─── WATCHDOG ─────────────────────────────────────────────────────────────────

def watchdog_loop():
    log.info("[Watchdog] ⌚ Attend token OAuth...")
    _setup_done.wait()
    log.info("[Watchdog] ✅ Token OK — surveillance active !")

    tracks  = []
    retries = 0

    while True:
        try:
            sp = get_sp()

            # Charge les tracks une fois
            if not tracks:
                tracks = get_artist_tracks(sp)
                if not tracks:
                    log.warning("[Watchdog] ⚠️ Aucune track — retry 60s")
                    time.sleep(60)
                    continue

            # État de lecture actuel
            playback   = sp.current_playback()
            is_playing = playback is not None and playback.get("is_playing")

            if not is_playing:
                # Cherche un device dispo
                device_id = get_any_device(sp)
                if not device_id:
                    log.warning("[Watchdog] 💤 Aucun device actif — ouvre Spotify sur ton tel !")
                    time.sleep(30)
                    continue

                device_name = next(
                    (d["name"] for d in sp.devices()["devices"] if d["id"] == device_id),
                    device_id
                )
                shuffled = random.sample(tracks, min(len(tracks), 50))
                sp.start_playback(device_id=device_id, uris=shuffled)
                sp.shuffle(True, device_id=device_id)
                sp.repeat("context", device_id=device_id)
                log.info(f"[Watchdog] ▶️ Lecture lancée sur '{device_name}' !")
                retries = 0

            else:
                track  = playback["item"]["name"]
                device = playback["device"]["name"]
                log.info(f"[Watchdog] ✅ {track} — sur '{device}'")

        except Exception as e:
            retries += 1
            log.error(f"[Watchdog] ❌ Erreur #{retries}: {e}")
            if retries > 10:
                retries = 0

        time.sleep(30)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 55)
    log.info("🎵 SPOTIFY FARMER v3 — Starting up...")
    log.info(f"   Artist  : {ARTIST_ID}")
    log.info(f"   URL     : https://{RAILWAY_DOMAIN or f'localhost:{PORT}'}")
    log.info("=" * 55)

    if oauth.get_cached_token():
        log.info("[Main] ✅ Token en cache !")
        _setup_done.set()
    else:
        log.info(f"[Main] 🔐 Auth requise → https://{RAILWAY_DOMAIN or f'localhost:{PORT}'}")

    t = threading.Thread(target=watchdog_loop, daemon=True)
    t.start()

    app.run(host="0.0.0.0", port=PORT, debug=False)


if __name__ == "__main__":
    main()
