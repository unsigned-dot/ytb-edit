"""Modèles de données.

Les temps sont des secondes entières (``int``) : la précision à la seconde
suffit pour la V1. Les modèles ne contiennent pas de logique métier, seulement
des propriétés de lecture et la table des transitions d'état autorisées.
"""

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TypeVar

from ytb_edit.core.errors import InvalidStateTransitionError


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class OutputMode(StrEnum):
    AUDIO_VIDEO = "audio_video"
    VIDEO_ONLY = "video_only"
    AUDIO_ONLY = "audio_only"

    @property
    def needs_video(self) -> bool:
        return self is not OutputMode.AUDIO_ONLY

    @property
    def needs_audio(self) -> bool:
        return self is not OutputMode.VIDEO_ONLY


class AudioFormat(StrEnum):
    """Format de sortie du mode « audio seul »."""

    M4A = "m4a"  # piste AAC d'origine, sans réencodage
    MP3 = "mp3"  # réencodage de l'audio (compatibilité maximale)


class TaskStatus(StrEnum):
    FETCHING_INFO = "fetching_info"  # récupération des métadonnées
    READY = "ready"  # métadonnées OK, pas de source local
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"  # source local disponible, segments en attente
    PROCESSING = "processing"  # un segment de cette vidéo est en cours de découpe
    COMPLETED = "completed"  # plus aucun segment en attente (réouvrable)
    FAILED = "failed"
    CANCELLED = "cancelled"


class SegmentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TS = TaskStatus
TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    _TS.FETCHING_INFO: frozenset({_TS.READY, _TS.FAILED, _TS.CANCELLED}),
    # READY → DOWNLOADED : source déjà présent dans le cache.
    _TS.READY: frozenset({_TS.DOWNLOADING, _TS.DOWNLOADED, _TS.CANCELLED}),
    _TS.DOWNLOADING: frozenset({_TS.DOWNLOADED, _TS.FAILED, _TS.CANCELLED}),
    # DOWNLOADED → DOWNLOADING : changement de mode nécessitant une piste manquante.
    _TS.DOWNLOADED: frozenset({_TS.PROCESSING, _TS.COMPLETED, _TS.DOWNLOADING, _TS.CANCELLED}),
    _TS.PROCESSING: frozenset({_TS.DOWNLOADED, _TS.COMPLETED, _TS.FAILED, _TS.CANCELLED}),
    # Nouveau segment : source présent → DOWNLOADED, source purgé → READY.
    _TS.COMPLETED: frozenset({_TS.DOWNLOADED, _TS.READY}),
    # « Réessayer » : on reprend là où ça a échoué.
    _TS.FAILED: frozenset({_TS.FETCHING_INFO, _TS.READY}),
    _TS.CANCELLED: frozenset({_TS.FETCHING_INFO, _TS.READY}),
}

_SS = SegmentStatus
SEGMENT_TRANSITIONS: dict[SegmentStatus, frozenset[SegmentStatus]] = {
    _SS.PENDING: frozenset({_SS.PROCESSING, _SS.CANCELLED}),
    # PROCESSING → PENDING : découpe interrompue sans faute (ex. arrêt), à refaire.
    _SS.PROCESSING: frozenset({_SS.DONE, _SS.FAILED, _SS.CANCELLED, _SS.PENDING}),
    _SS.DONE: frozenset(),
    _SS.FAILED: frozenset({_SS.PENDING}),
    _SS.CANCELLED: frozenset({_SS.PENDING}),
}


_S = TypeVar("_S", TaskStatus, SegmentStatus)


def check_transition(current: _S, new: _S) -> _S:
    """Renvoie ``new`` si la transition est autorisée, lève une erreur sinon."""
    table = TASK_TRANSITIONS if isinstance(current, TaskStatus) else SEGMENT_TRANSITIONS
    if new not in table[current]:
        raise InvalidStateTransitionError(
            "Erreur interne (voir les logs).",
            details=f"Transition interdite : {current!r} -> {new!r}",
        )
    return new


@dataclass(frozen=True, slots=True)
class VideoInfo:
    """Métadonnées d'une vidéo, telles que récupérées avant téléchargement."""

    video_id: str
    url: str
    title: str
    duration_s: int
    has_video: bool
    has_audio: bool
    uploader: str | None = None
    estimated_size: int | None = None  # octets, si YouTube l'annonce


@dataclass(frozen=True, slots=True)
class SourceFiles:
    """Pistes téléchargées dans le cache. Peut contenir la vidéo, l'audio ou les deux."""

    video_path: Path | None = None
    audio_path: Path | None = None

    def covers(self, mode: OutputMode) -> bool:
        """Les pistes présentes suffisent-elles pour produire ce mode ?"""
        return (not mode.needs_video or self.video_path is not None) and (
            not mode.needs_audio or self.audio_path is not None
        )


@dataclass(slots=True)
class Segment:
    number: int  # numéro de clip stable (clip_001…), jamais renuméroté
    start_s: int
    end_s: int
    mode: OutputMode
    id: str = field(default_factory=new_id)
    status: SegmentStatus = SegmentStatus.PENDING
    actual_start_s: int | None = None  # début réel après alignement sur l'image clé
    output_path: Path | None = None
    error: str | None = None

    @property
    def duration_s(self) -> int:
        return self.end_s - self.start_s


@dataclass(slots=True)
class VideoTask:
    url: str
    mode: OutputMode
    id: str = field(default_factory=new_id)
    status: TaskStatus = TaskStatus.FETCHING_INFO
    info: VideoInfo | None = None
    segments: list[Segment] = field(default_factory=list)
    source: SourceFiles | None = None
    download_progress: float = 0.0  # 0.0 → 1.0
    error: str | None = None
    next_segment_number: int = 1

    @property
    def title(self) -> str:
        return self.info.title if self.info else self.url

    def count(self, status: SegmentStatus) -> int:
        return sum(1 for s in self.segments if s.status is status)
