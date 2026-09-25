"""Noms de fichiers Windows, nommage des clips, chemins uniques, espace disque."""

import re
import shutil
import unicodedata
from pathlib import Path

from ytb_edit.core.errors import DiskSpaceError
from ytb_edit.core.timecode import format_for_filename

MAX_NAME_LENGTH = 80
# Windows limite classiquement les chemins à 260 caractères (MAX_PATH).
MAX_PATH_LENGTH = 250
CLIP_NAME_RESERVE = 45  # longueur maximale d'un nom de clip, suffixe compris

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{p}{i}" for p in ("COM", "LPT") for i in [*"123456789", "¹", "²", "³"]
}


def sanitize_filename(
    name: str, *, fallback: str = "video", max_length: int = MAX_NAME_LENGTH
) -> str:
    """Rend un texte utilisable comme nom de fichier/dossier Windows."""
    cleaned = _clean(name, max_length)
    if not cleaned.strip("_. "):
        cleaned = _clean(fallback, max_length).strip("_. ") or "video"
    if cleaned.split(".")[0].upper() in _RESERVED:
        cleaned = f"{cleaned}_"
    return cleaned


def _clean(name: str, max_length: int) -> str:
    cleaned = unicodedata.normalize("NFC", name)
    cleaned = " ".join(cleaned.split())  # espaces multiples, tabulations, retours
    cleaned = _FORBIDDEN.sub("_", cleaned)
    # Windows interdit les points et espaces en fin de nom.
    return cleaned[:max_length].rstrip(" .")


def video_output_dir(output_root: Path, title: str, video_id: str) -> Path:
    """Dossier de sortie d'une vidéo : ``<racine>/<titre nettoyé>``.

    Le titre est raccourci si nécessaire pour que les chemins restent sous MAX_PATH.
    """
    # deux séparateurs : racine/titre et titre/clip
    budget = MAX_PATH_LENGTH - len(str(output_root)) - 2 - CLIP_NAME_RESERVE
    max_length = max(8, min(MAX_NAME_LENGTH, budget))
    return output_root / sanitize_filename(title, fallback=video_id, max_length=max_length)


def clip_filename(number: int, start_s: int, end_s: int, *, with_hours: bool, ext: str) -> str:
    """``clip_001_03m20s-03m50s.mp4`` (heures incluses si la vidéo dure ≥ 1 h)."""
    start = format_for_filename(start_s, with_hours=with_hours)
    end = format_for_filename(end_s, with_hours=with_hours)
    return f"clip_{number:03d}_{start}-{end}.{ext.lstrip('.')}"


def unique_path(path: Path) -> Path:
    """Renvoie ``path`` s'il est libre, sinon ``nom_1.ext``, ``nom_2.ext``…"""
    if not path.exists():
        return path
    index = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def free_space(path: Path) -> int:
    """Espace libre (octets) du disque contenant ``path`` (même s'il n'existe pas encore)."""
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def ensure_free_space(path: Path, needed_bytes: int) -> None:
    available = free_space(path)
    if available < needed_bytes:
        raise DiskSpaceError(
            f"Espace disque insuffisant : {_human(needed_bytes)} nécessaires, "
            f"{_human(available)} disponibles sur {path.anchor or path}.",
            details=f"path={path} needed={needed_bytes} free={available}",
        )


def _human(size: int) -> str:
    value = float(size)
    for unit in ("o", "Ko", "Mo", "Go"):
        if value < 1024:
            return f"{value:.0f} {unit}"
        value /= 1024
    return f"{value:.1f} To"
