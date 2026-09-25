"""Choix de la prochaine opération : fonctions pures, testables sans threads.

Ordre de traitement : ordre des vidéos dans la file, puis numéro de segment.
"""

from collections.abc import Iterable

from ytb_edit.core.models import (
    Segment,
    SegmentStatus,
    SourceFiles,
    TaskStatus,
    VideoTask,
)


def pending_segments(task: VideoTask) -> list[Segment]:
    return [s for s in task.segments if s.status is SegmentStatus.PENDING]


def missing_streams(task: VideoTask) -> tuple[bool, bool]:
    """Pistes (vidéo, audio) nécessaires aux segments en attente mais absentes."""
    pending = pending_segments(task)
    need_video = any(s.mode.needs_video for s in pending)
    need_audio = any(s.mode.needs_audio for s in pending)
    source = task.source or SourceFiles()
    return (need_video and source.video_path is None, need_audio and source.audio_path is None)


def next_info_task(tasks: Iterable[VideoTask], in_flight: set[str]) -> VideoTask | None:
    return next(
        (t for t in tasks if t.status is TaskStatus.FETCHING_INFO and t.id not in in_flight),
        None,
    )


def next_download_task(tasks: Iterable[VideoTask]) -> VideoTask | None:
    for task in tasks:
        if task.status is TaskStatus.READY and pending_segments(task):
            return task
        if task.status is TaskStatus.DOWNLOADED and any(missing_streams(task)):
            return task
    return None


def next_cut(tasks: Iterable[VideoTask]) -> tuple[VideoTask, Segment] | None:
    for task in tasks:
        if task.status is not TaskStatus.DOWNLOADED or task.source is None:
            continue
        for segment in task.segments:
            if segment.status is SegmentStatus.PENDING and task.source.covers(segment.mode):
                return task, segment
    return None
