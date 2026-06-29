import logging
import os
import time


import spotipy
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from spotipy.oauth2 import SpotifyOAuth

load_dotenv()

# ── Logging (nunca a stdout, siempre a archivo) ───────────────────────────────

logging.basicConfig(
    filename=os.path.join(os.path.dirname(__file__), "server.log"),
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Auth Spotify ──────────────────────────────────────────────────────────────

SCOPE = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing "
    "playlist-read-private "
    "playlist-read-collaborative"
)

sp = spotipy.Spotify(
    auth_manager=SpotifyOAuth(
        client_id=os.getenv("SPOTIPY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIPY_CLIENT_SECRET"),
        redirect_uri="http://127.0.0.1:8080",
        scope=SCOPE,
        cache_path=os.path.join(os.path.dirname(__file__), ".cache"),
    )
)

mcp = FastMCP("SpotifyServer")


# ── Helper ────────────────────────────────────────────────────────────────────


def _active_device() -> str | None:
    """Devuelve el device_id del dispositivo activo, o None si no hay ninguno."""
    devices = sp.devices()
    if not devices or "devices" not in devices:
        log.warning("No se encontraron dispositivos.")
        return None

    for d in devices.get("devices", []):
        if d["is_active"]:
            log.debug("Dispositivo activo: %s (%s)", d["name"], d["id"])
            return d["id"]

    devs = devices.get("devices", [])
    if devs:
        log.debug("Ninguno activo, usando primero: %s", devs[0]["name"])
        return devs[0]["id"]

    return None


# ── Tools de información ──────────────────────────────────────────────────────


@mcp.tool()
def get_current_track() -> str:
    """Devuelve la canción que está sonando ahora mismo."""
    log.debug("get_current_track llamado")
    current = sp.current_playback()
    if not current or not current.get("item"):
        return "No hay nada reproduciéndose en este momento."

    item = current["item"]
    artists = ", ".join(a["name"] for a in item.get("artists", []))
    track = item.get("name", "Desconocido")
    album = item.get("album", {}).get("name", "Desconocido")
    is_playing = "▶ Reproduciendo" if current.get("is_playing") else "⏸ Pausado"
    progress_ms = current.get("progress_ms", 0)
    duration_ms = item.get("duration_ms", 0)
    progress_s = progress_ms // 1000
    duration_s = duration_ms // 1000
    volume = current.get("device", {}).get("volume_percent", "?")
    device_name = current.get("device", {}).get("name", "?")

    return (
        f"{is_playing}: {track} — {artists}\n"
        f"Álbum: {album}\n"
        f"Progreso: {progress_s//60}:{progress_s%60:02d} / {duration_s//60}:{duration_s%60:02d}\n"
        f"Volumen: {volume}%  |  Dispositivo: {device_name}"
    )


@mcp.tool()
def list_devices() -> str:
    """Lista los dispositivos Spotify disponibles."""
    log.debug("list_devices llamado")
    devices_response = sp.devices()
    devices = devices_response.get("devices", []) if devices_response else []

    if not devices:
        return "No hay dispositivos Spotify disponibles. Abrí Spotify en algún dispositivo."

    lines = []
    for d in devices:
        active = " ← activo" if d.get("is_active") else ""
        lines.append(
            f"- {d.get('name')} ({d.get('type')}) vol:{d.get('volume_percent')}%{active}"
        )
    return "\n".join(lines)


@mcp.tool()
def search_track(query: str) -> str:
    """Busca una canción en Spotify y devuelve el URI para reproducirla."""
    log.debug("search_track: %s", query)
    results = sp.search(q=query, limit=5, type="track")
    if not results or "tracks" not in results or not results["tracks"]["items"]:
        return f"No encontré resultados para: {query}"

    tracks = results["tracks"]["items"]
    lines = []
    for t in tracks:
        artists = ", ".join(a["name"] for a in t.get("artists", []))
        lines.append(f"- {t.get('name')} — {artists}  [uri: {t.get('uri')}]")
    return "Resultados:\n" + "\n".join(lines)


@mcp.tool()
def search_playlist(query: str) -> str:
    """Busca una playlist en Spotify y devuelve el URI para reproducirla."""
    log.debug("search_playlist: %s", query)
    results = sp.search(q=query, limit=5, type="playlist")
    if not results or "playlists" not in results or not results["playlists"]["items"]:
        return f"No encontré playlists para: {query}"

    playlists = results["playlists"]["items"]
    lines = []
    for p in playlists:
        if not p:
            continue
        owner_data = p.get("owner") or {}
        owner = owner_data.get("display_name", "Desconocido")
        name = p.get("name", "Sin nombre")
        uri = p.get("uri", "")
        lines.append(f"- {name} (by {owner})  [uri: {uri}]")

    return "Playlists encontradas:\n" + "\n".join(lines)


@mcp.tool()
def get_my_playlists() -> str:
    """Devuelve las playlists del usuario autenticado con sus URIs.
    Usá siempre esta herramienta primero si el usuario pide reproducir
    'mi playlist' o 'mis playlists'."""
    log.debug("get_my_playlists llamado")
    results = sp.current_user_playlists(limit=50)
    if not results or "items" not in results or not results["items"]:
        return "No se pudieron obtener tus playlists."

    lines = []
    for p in results["items"]:
        if p:
            name = p.get("name", "Sin nombre")
            uri = p.get("uri", "")
            lines.append(f"- {name}  [uri: {uri}]")
    return "Tus playlists:\n" + "\n".join(lines)


# ── Tools de control ──────────────────────────────────────────────────────────


@mcp.tool()
def play(uri: str = "") -> str:
    """Reproduce una canción o playlist dado su URI de Spotify.
    Si no se pasa URI, reanuda la reproducción actual.
    Ejemplos de URI: spotify:track:xxx  o  spotify:playlist:xxx"""
    log.debug("play: uri=%r", uri)
    device_id = _active_device()
    if not device_id:
        return "No hay dispositivos Spotify disponibles. Abrí Spotify en algún dispositivo."

    try:
        if not uri:
            sp.start_playback(device_id=device_id)
            return "▶ Reproducción reanudada."

        if uri.startswith("spotify:track:"):
            sp.start_playback(device_id=device_id, uris=[uri])
            return f"▶ Reproduciendo track: {uri}"
        elif uri.startswith("spotify:playlist:") or uri.startswith("spotify:album:"):
            sp.start_playback(device_id=device_id, context_uri=uri)
            return f"▶ Reproduciendo contexto: {uri}"
        else:
            return (
                f"URI no reconocido: {uri}. "
                "Debe empezar con spotify:track:, spotify:playlist: o spotify:album:"
            )
    except Exception as e:
        log.error("Error en play: %s", e)
        return f"Error al reproducir: {e}"


@mcp.tool()
def pause() -> str:
    """Pausa la reproducción."""
    log.debug("pause llamado")
    device_id = _active_device()
    if not device_id:
        return "No hay dispositivos disponibles."
    sp.pause_playback(device_id=device_id)
    return "⏸ Pausado."


@mcp.tool()
def next_track() -> str:
    """Salta a la siguiente canción y devuelve el nombre del tema."""
    log.debug("next_track")
    device_id = _active_device()
    if not device_id:
        return "No hay dispositivos disponibles."
    
    sp.next_track(device_id=device_id)
    
    # Pausa de 0.5 a 1 segundo para dar tiempo a que Spotify actualice el estado
    time.sleep(1)
    
    playback = sp.current_playback()
    if playback and playback.get('item'):
        track_name = playback['item']['name']
        artist_name = playback['item']['artists'][0]['name']
        return f"⏭ Siguiente canción: {track_name} de {artist_name}"
        
    return "⏭ Siguiente canción." 


@mcp.tool()
def previous_track() -> str:
    """Vuelve a la canción anterior y devuelve el nombre del tema."""
    log.debug("previous_track")
    device_id = _active_device()
    if not device_id:
        return "No hay dispositivos disponibles."
    
    sp.previous_track(device_id=device_id)
    
    # Pausa de 1 segundo para dar tiempo a que Spotify actualice el estado
    time.sleep(1)
    
    playback = sp.current_playback()
    if playback and playback.get('item'):
        track_name = playback['item']['name']
        artist_name = playback['item']['artists'][0]['name']
        return f"⏮ Canción anterior: {track_name} de {artist_name}"
        
    return "⏮ Canción anterior."

@mcp.tool()
def set_volume(volume_percent: int) -> str:
    """Ajusta el volumen. Valor entre 0 y 100."""
    log.debug("set_volume: %d", volume_percent)
    if not 0 <= volume_percent <= 100:
        return "El volumen debe estar entre 0 y 100."
    device_id = _active_device()
    if not device_id:
        return "No hay dispositivos disponibles."
    sp.volume(volume_percent, device_id=device_id)
    return f"🔊 Volumen ajustado a {volume_percent}%."


@mcp.tool()
def set_shuffle(state: bool) -> str:
    """Activa o desactiva el modo aleatorio (shuffle)."""
    log.debug("set_shuffle: %s", state)
    device_id = _active_device()
    if not device_id:
        return "No hay dispositivos disponibles."

    # Validación
    playback = sp.current_playback()
    if playback is not None:
        actual_state = playback.get("shuffle_state", False)
        if actual_state == state:
            return f"El shuffle ya estaba {'activado' if state else 'desactivado'}."

    sp.shuffle(state, device_id=device_id)
    return f"🔀 Shuffle {'activado' if state else 'desactivado'}."


@mcp.tool()
def set_repeat(mode: str) -> str:
    """Cambia el modo de repetición.
    Valores válidos: 'off', 'track', 'context'
    - off: sin repetición
    - track: repite la canción actual
    - context: repite el álbum/playlist"""
    log.debug("set_repeat: %s", mode)
    if mode not in ("off", "track", "context"):
        return "Modo inválido. Usá: 'off', 'track' o 'context'."
    device_id = _active_device()
    if not device_id:
        return "No hay dispositivos disponibles."
    sp.repeat(mode, device_id=device_id)
    labels = {
        "off": "desactivada",
        "track": "repitiendo esta canción",
        "context": "repitiendo playlist/álbum",
    }
    return f"🔁 Repetición {labels[mode]}."


if __name__ == "__main__":
    mcp.run(transport="stdio")