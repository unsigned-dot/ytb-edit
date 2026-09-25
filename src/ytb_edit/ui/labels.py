"""Textes affichés pour les états (centralisés pour rester cohérents)."""

from ytb_edit.core.models import OutputMode, Segment, SegmentStatus, TaskStatus, VideoTask
from ytb_edit.core.timecode import format_time

MODE_LABELS = {
    OutputMode.AUDIO_VIDEO: "Vidéo + audio",
    OutputMode.VIDEO_ONLY: "Vidéo seule",
    OutputMode.AUDIO_ONLY: "Audio seul",
}

TASK_LABELS = {
    TaskStatus.FETCHING_INFO: "⏳ Récupération des infos…",
    TaskStatus.READY: "○ En attente",
    TaskStatus.DOWNLOADING: "⏳ Téléchargement",
    TaskStatus.DOWNLOADED: "○ Prête à découper",
    TaskStatus.PROCESSING: "⏳ Découpe",
    TaskStatus.COMPLETED: "✓ Terminée",
    TaskStatus.FAILED: "✗ Erreur",
    TaskStatus.CANCELLED: "⊘ Annulée",
}

SEGMENT_ICONS = {
    SegmentStatus.PENDING: "○",
    SegmentStatus.PROCESSING: "⏳",
    SegmentStatus.DONE: "✓",
    SegmentStatus.FAILED: "✗",
    SegmentStatus.CANCELLED: "⊘",
}

SEGMENT_LABELS = {
    SegmentStatus.PENDING: "En attente",
    SegmentStatus.PROCESSING: "Découpe…",
    SegmentStatus.DONE: "Créé",
    SegmentStatus.FAILED: "Erreur",
    SegmentStatus.CANCELLED: "Annulé",
}


def task_status_text(task: VideoTask) -> str:
    text = TASK_LABELS[task.status]
    if task.status is TaskStatus.COMPLETED and task.count(SegmentStatus.FAILED):
        text = "⚠ Terminée avec erreurs"
    return text


def segment_text(segment: Segment) -> str:
    return (
        f"{SEGMENT_ICONS[segment.status]}  #{segment.number:03d}   "
        f"{format_time(segment.start_s)} → {format_time(segment.end_s)}"
    )


def segments_progress(task: VideoTask) -> str:
    active = [s for s in task.segments if s.status is not SegmentStatus.CANCELLED]
    if not active:
        return ""
    return f"{task.count(SegmentStatus.DONE)}/{len(active)} segments"
