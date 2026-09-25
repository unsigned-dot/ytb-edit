"""Événements émis par le moteur vers l'interface.

Les tâches transmises sont des copies figées : l'interface ne peut pas modifier
l'état du moteur par erreur.
"""

from dataclasses import dataclass, field

from ytb_edit.core.models import VideoTask


@dataclass(frozen=True)
class TaskChanged:
    task: VideoTask  # copie


@dataclass(frozen=True)
class TaskRemoved:
    task_id: str


@dataclass(frozen=True)
class Progress:
    """Avancement de l'opération en cours sur une tâche (téléchargement ou découpe)."""

    task_id: str
    fraction: float
    text: str


@dataclass(frozen=True)
class Notice:
    """Message destiné à l'utilisateur (zone « Activité »)."""

    text: str
    error: bool = False


@dataclass(frozen=True)
class QueueStateChanged:
    running: bool


@dataclass(frozen=True)
class Summary:
    videos: int
    videos_ok: int
    clips: int
    errors: int
    lines: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class QueueIdle:
    summary: Summary


Event = TaskChanged | TaskRemoved | Progress | Notice | QueueStateChanged | QueueIdle
