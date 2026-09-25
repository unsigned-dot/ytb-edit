"""Accès à YouTube via yt-dlp : validation d'URL, métadonnées (et, à l'étape 5,
téléchargement).

Uniquement des vidéos publiques ou non répertoriées, sans cookies ni
authentification. Les vidéos protégées (DRM, restriction d'âge, membres…) sont
refusées avec un message explicite : aucun contournement n'est tenté.
"""

import logging
import math
import re
import shutil
from typing import Any
from urllib.parse import parse_qs, urlsplit

import yt_dlp
from yt_dlp.utils import DownloadError as YtDlpDownloadError

from ytb_edit.core.errors import (
    AppError,
    InvalidUrlError,
    NetworkError,
    UnsupportedVideoError,
    VideoUnavailableError,
    YouTubeError,
)
from ytb_edit.core.models import VideoInfo

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# URL
# ---------------------------------------------------------------------------

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_LONG_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
_ID_PATH_PREFIXES = {"shorts", "live", "embed", "v"}


def parse_video_id(text: str) -> str:
    """Extrait l'identifiant (11 caractères) d'une URL de vidéo YouTube.

    Les paramètres annexes (``t=``, ``list=``, ``si=``…) sont ignorés : seule la
    vidéo désignée est traitée, jamais la playlist.
    """
    raw = text.strip()
    if not raw:
        raise InvalidUrlError("URL vide.")
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower()
    except ValueError as exc:
        raise InvalidUrlError("URL invalide.", details=str(exc)) from exc

    if parts.scheme not in ("http", "https") or not (host in _LONG_HOSTS or host in _SHORT_HOSTS):
        raise InvalidUrlError("Ce n'est pas une URL YouTube.", details=text)

    path_parts = [p for p in parts.path.split("/") if p]
    candidate = ""
    if host in _SHORT_HOSTS:
        candidate = path_parts[0] if path_parts else ""
    elif path_parts == ["watch"]:
        candidate = parse_qs(parts.query).get("v", [""])[0]
    elif len(path_parts) >= 2 and path_parts[0] in _ID_PATH_PREFIXES:
        candidate = path_parts[1]

    if not _VIDEO_ID.fullmatch(candidate):
        raise InvalidUrlError(
            "Cette URL ne désigne pas une vidéo YouTube "
            "(les playlists et les chaînes ne sont pas prises en charge).",
            details=text,
        )
    return candidate


def canonical_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


# ---------------------------------------------------------------------------
# Configuration de yt-dlp
# ---------------------------------------------------------------------------

# yt-dlp a besoin d'un moteur JavaScript pour lire correctement YouTube.
# Deno est celui qu'il utilise par défaut ; Node et Bun sont aussi acceptés.
JS_RUNTIMES = ("deno", "node", "bun")


def find_js_runtime() -> tuple[str, str] | None:
    """Renvoie ``(nom, chemin)`` du premier moteur JavaScript trouvé dans le PATH."""
    for name in JS_RUNTIMES:
        if path := shutil.which(name):
            return name, path
    return None


def ytdlp_version() -> str:
    return yt_dlp.version.__version__


class _YtDlpLogger:
    """Redirige les messages de yt-dlp vers le logging standard (fichier de logs)."""

    _log = logging.getLogger("yt_dlp")

    def debug(self, msg: str) -> None:
        # yt-dlp envoie aussi ses messages d'information via debug().
        if msg.startswith("[debug] "):
            self._log.debug(msg[8:])
        else:
            self._log.info(msg)

    def info(self, msg: str) -> None:
        self._log.info(msg)

    def warning(self, msg: str) -> None:
        self._log.warning(msg)

    def error(self, msg: str) -> None:
        self._log.error(msg)


def base_options() -> dict[str, Any]:
    """Options communes à toutes les utilisations de yt-dlp."""
    options: dict[str, Any] = {
        "logger": _YtDlpLogger(),
        "noplaylist": True,
        "noprogress": True,
        "socket_timeout": 20,
        "retries": 5,
    }
    if runtime := find_js_runtime():
        name, path = runtime
        options["js_runtimes"] = {name: {"path": path}}
    else:
        log.warning("Aucun moteur JavaScript (deno/node/bun) : formats YouTube limités.")
    return options


# ---------------------------------------------------------------------------
# Métadonnées
# ---------------------------------------------------------------------------


def fetch_video_info(video_id: str, *, ydl_class: type = yt_dlp.YoutubeDL) -> VideoInfo:
    """Récupère et valide les métadonnées d'une vidéo, sans rien télécharger.

    ``ydl_class`` permet d'injecter un faux yt-dlp dans les tests.
    """
    url = canonical_url(video_id)
    log.info("Récupération des métadonnées : %s", url)
    options = base_options() | {"skip_download": True}
    try:
        with ydl_class(options) as ydl:
            raw = ydl.extract_info(url, download=False)
    except YtDlpDownloadError as exc:
        raise translate_ytdlp_error(exc) from exc
    info = video_info_from_ytdlp(raw)
    log.info(
        "Métadonnées OK : %r (%s s, vidéo=%s, audio=%s)",
        info.title,
        info.duration_s,
        info.has_video,
        info.has_audio,
    )
    return info


def video_info_from_ytdlp(raw: dict[str, Any]) -> VideoInfo:
    """Transforme le dictionnaire de yt-dlp en ``VideoInfo`` après validation."""
    video_id = raw.get("id") or ""

    live_status = raw.get("live_status")
    if live_status == "is_live":
        raise UnsupportedVideoError("Les directs en cours ne sont pas pris en charge.")
    if live_status == "is_upcoming":
        raise UnsupportedVideoError("Vidéo pas encore disponible (direct ou première à venir).")
    if live_status == "post_live":
        raise UnsupportedVideoError(
            "Direct terminé, encore en traitement par YouTube. Réessayez plus tard."
        )

    availability = raw.get("availability")
    if availability == "private":
        raise VideoUnavailableError("Vidéo privée.")
    if availability in ("premium_only", "subscriber_only", "needs_auth"):
        raise UnsupportedVideoError(
            "Vidéo à accès restreint (compte, abonnement ou membres) : non prise en charge.",
            details=f"availability={availability}",
        )

    all_formats = raw.get("formats") or []
    formats = [f for f in all_formats if not f.get("has_drm")]
    if all_formats and not formats:
        raise UnsupportedVideoError("Vidéo protégée par DRM : non prise en charge.")

    video_formats = [f for f in formats if _has_codec(f, "vcodec")]
    audio_formats = [f for f in formats if _has_codec(f, "acodec")]
    if not video_formats and not audio_formats:
        raise YouTubeError(
            "Aucun format téléchargeable pour cette vidéo.",
            details=f"{len(all_formats)} formats reçus",
        )

    duration = raw.get("duration")
    if not duration:
        raise UnsupportedVideoError("Durée de la vidéo inconnue : non prise en charge.")

    audio_only = [f for f in audio_formats if not _has_codec(f, "vcodec")]
    estimated = _largest_size(video_formats) + _largest_size(audio_only)

    return VideoInfo(
        video_id=video_id,
        url=canonical_url(video_id),
        title=raw.get("title") or video_id,
        # Arrondi supérieur : un segment peut toujours aller jusqu'à la toute fin.
        duration_s=math.ceil(duration),
        has_video=bool(video_formats),
        has_audio=bool(audio_formats),
        uploader=raw.get("uploader") or raw.get("channel"),
        estimated_size=estimated or None,
    )


def _has_codec(fmt: dict[str, Any], key: str) -> bool:
    return fmt.get(key) not in (None, "none")


def _largest_size(formats: list[dict[str, Any]]) -> int:
    return max((f.get("filesize") or f.get("filesize_approx") or 0 for f in formats), default=0)


# ---------------------------------------------------------------------------
# Traduction des erreurs
# ---------------------------------------------------------------------------

_NETWORK_MESSAGE = "Problème de connexion réseau. Vérifiez votre connexion puis réessayez."

# Ordre important : du plus spécifique au plus général.
_ERROR_RULES: list[tuple[re.Pattern[str], type[AppError], str]] = [
    (re.compile(r"private video"), VideoUnavailableError, "Vidéo privée."),
    (
        re.compile(r"confirm your age|age[- ]restricted|inappropriate for some users"),
        UnsupportedVideoError,
        "Vidéo soumise à une restriction d'âge : non prise en charge.",
    ),
    (
        re.compile(r"members[- ]only|join this channel|available to this channel's members"),
        UnsupportedVideoError,
        "Vidéo réservée aux membres : non prise en charge.",
    ),
    (
        re.compile(r"\bdrm\b"),
        UnsupportedVideoError,
        "Vidéo protégée par DRM : non prise en charge.",
    ),
    (
        re.compile(r"live event will begin|premieres in|this live event"),
        UnsupportedVideoError,
        "Vidéo pas encore disponible (direct ou première à venir).",
    ),
    (
        re.compile(r"not made this video available in your country|not available in your country"),
        UnsupportedVideoError,
        "Vidéo non disponible dans votre pays.",
    ),
    (
        re.compile(r"not a bot"),
        YouTubeError,
        "YouTube demande une vérification anti-robot. Réessayez plus tard.",
    ),
    (
        re.compile(r"http error 429|too many requests"),
        NetworkError,
        "YouTube limite temporairement les requêtes. Réessayez plus tard.",
    ),
    (
        re.compile(
            r"video unavailable|video is unavailable|has been removed|been terminated"
            r"|does not exist|no longer available|video is not available"
        ),
        VideoUnavailableError,
        "Vidéo indisponible (supprimée, privée ou inexistante).",
    ),
    (
        re.compile(
            r"unable to connect|timed out|connection (?:reset|refused|aborted)"
            r"|getaddrinfo failed|name resolution|network is unreachable|urlopen error"
            r"|remote end closed|ssl|unable to download (?:webpage|api page)"
        ),
        NetworkError,
        _NETWORK_MESSAGE,
    ),
    (
        re.compile(r"requested format is not available|no video formats found"),
        YouTubeError,
        "Aucun format disponible pour cette vidéo. Mettre à jour yt-dlp peut aider.",
    ),
]


def translate_ytdlp_error(exc: Exception) -> AppError:
    """Convertit une erreur yt-dlp en ``AppError`` avec un message utilisateur clair."""
    message = str(exc)
    lowered = message.lower()
    for pattern, error_class, user_message in _ERROR_RULES:
        if pattern.search(lowered):
            return error_class(user_message, details=message)
    return YouTubeError(
        "Impossible de récupérer la vidéo (voir les logs). Mettre à jour yt-dlp peut aider.",
        details=message,
    )
