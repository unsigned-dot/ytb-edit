"""Cache des fichiers sources téléchargés, un dossier par identifiant YouTube.

    <cache>/<video_id>/
        video.<format>.webm     piste(s) téléchargée(s)
        audio.<format>.m4a
        source.json             écrit seulement après validation

Le cache est une optimisation : s'il manque ou est purgé, la vidéo est
simplement retéléchargée.
"""

import json
import logging
import shutil
from pathlib import Path

from ytb_edit.core.models import SourceFiles

log = logging.getLogger(__name__)

MARKER = "source.json"


class SourceCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def dir_for(self, video_id: str) -> Path:
        return self.root / video_id

    def load(self, video_id: str) -> SourceFiles | None:
        """Sources validées présentes pour cette vidéo, ou ``None``."""
        marker = self.dir_for(video_id) / MARKER
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        directory = self.dir_for(video_id)
        video = _existing(directory, data.get("video"))
        audio = _existing(directory, data.get("audio"))
        if video is None and audio is None:
            return None
        return SourceFiles(video_path=video, audio_path=audio)

    def save(self, video_id: str, source: SourceFiles) -> None:
        directory = self.dir_for(video_id)
        data = {
            "video": source.video_path.name if source.video_path else None,
            "audio": source.audio_path.name if source.audio_path else None,
        }
        tmp = directory / (MARKER + ".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(directory / MARKER)

    def delete(self, video_id: str) -> bool:
        """Supprime les sources d'une vidéo. Un échec est journalisé, jamais levé."""
        directory = self.dir_for(video_id)
        if not directory.exists():
            return True
        try:
            shutil.rmtree(directory)
            log.info("Cache supprimé : %s", directory)
            return True
        except OSError as exc:
            log.warning("Suppression du cache impossible (%s) : %s", directory, exc)
            return False

    def size_of(self, video_id: str) -> int:
        return _dir_size(self.dir_for(video_id))

    def total_size(self) -> int:
        return _dir_size(self.root)

    def purge_incomplete(self) -> None:
        """Au démarrage : supprime les téléchargements interrompus d'une session précédente."""
        if not self.root.exists():
            return
        for directory in self.root.iterdir():
            if not directory.is_dir():
                continue
            if not (directory / MARKER).exists():
                self.delete(directory.name)
                continue
            for leftover in directory.glob("*.part*"):
                try:
                    leftover.unlink()
                except OSError as exc:
                    log.warning("Fichier temporaire non supprimé %s : %s", leftover, exc)

    def delete_all(self) -> None:
        if self.root.exists():
            for directory in self.root.iterdir():
                if directory.is_dir():
                    self.delete(directory.name)


def _existing(directory: Path, name: str | None) -> Path | None:
    if not name:
        return None
    path = directory / name
    return path if path.is_file() and path.stat().st_size > 0 else None


def _dir_size(directory: Path) -> int:
    if not directory.exists():
        return 0
    total = 0
    for path in directory.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            pass
    return total
