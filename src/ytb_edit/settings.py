"""Préférences utilisateur, mémorisées dans un fichier JSON.

Emplacement : %APPDATA%\\ytb-edit\\settings.json. Un fichier absent ou illisible
n'empêche jamais le démarrage : on repart des valeurs par défaut.
"""

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from ytb_edit import paths
from ytb_edit.core.models import AudioFormat, OutputMode

log = logging.getLogger(__name__)

SETTINGS_FILE_NAME = "settings.json"


@dataclass
class AppSettings:
    output_dir: str = ""
    cache_dir: str = ""  # vide = emplacement par défaut
    default_mode: str = OutputMode.AUDIO_VIDEO.value
    audio_format: str = AudioFormat.M4A.value
    keep_cache_on_exit: bool = False
    cache_limit_gb: int = 20
    ffmpeg_dir: str = ""  # vide = recherche automatique

    @property
    def effective_cache_dir(self) -> Path:
        return Path(self.cache_dir) if self.cache_dir else paths.default_cache_dir()

    @property
    def mode(self) -> OutputMode:
        try:
            return OutputMode(self.default_mode)
        except ValueError:
            return OutputMode.AUDIO_VIDEO

    @property
    def audio(self) -> AudioFormat:
        try:
            return AudioFormat(self.audio_format)
        except ValueError:
            return AudioFormat.M4A


def settings_path() -> Path:
    return paths.config_dir() / SETTINGS_FILE_NAME


def load_settings(path: Path | None = None) -> AppSettings:
    path = path or settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return AppSettings()
    except (OSError, ValueError) as exc:
        log.warning("Paramètres illisibles (%s), valeurs par défaut utilisées", exc)
        return AppSettings()
    if not isinstance(data, dict):
        return AppSettings()
    defaults = AppSettings()
    known = {}
    for f in fields(AppSettings):
        value = data.get(f.name, getattr(defaults, f.name))
        # Protection contre un fichier édité à la main avec un mauvais type.
        known[f.name] = (
            value if type(value) is type(getattr(defaults, f.name)) else getattr(defaults, f.name)
        )
    return AppSettings(**known)


def save_settings(settings: AppSettings, path: Path | None = None) -> None:
    path = path or settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), "utf-8")
        tmp.replace(path)
    except OSError:
        log.exception("Impossible d'enregistrer les paramètres")
