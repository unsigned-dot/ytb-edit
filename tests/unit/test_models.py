import itertools
from pathlib import Path

import pytest

from ytb_edit.core.errors import InvalidStateTransitionError
from ytb_edit.core.models import (
    SEGMENT_TRANSITIONS,
    TASK_TRANSITIONS,
    OutputMode,
    Segment,
    SegmentStatus,
    SourceFiles,
    TaskStatus,
    VideoInfo,
    VideoTask,
    check_transition,
)


def test_transition_tables_cover_every_status():
    assert set(TASK_TRANSITIONS) == set(TaskStatus)
    assert set(SEGMENT_TRANSITIONS) == set(SegmentStatus)


@pytest.mark.parametrize(
    "path",
    [
        # parcours nominal
        [
            TaskStatus.FETCHING_INFO,
            TaskStatus.READY,
            TaskStatus.DOWNLOADING,
            TaskStatus.DOWNLOADED,
            TaskStatus.PROCESSING,
            TaskStatus.DOWNLOADED,
            TaskStatus.PROCESSING,
            TaskStatus.COMPLETED,
        ],
        # source déjà en cache
        [TaskStatus.READY, TaskStatus.DOWNLOADED],
        # segment ajouté après la fin, source encore présent / purgé
        [TaskStatus.COMPLETED, TaskStatus.DOWNLOADED, TaskStatus.PROCESSING],
        [TaskStatus.COMPLETED, TaskStatus.READY, TaskStatus.DOWNLOADING],
        # échec puis « Réessayer »
        [TaskStatus.DOWNLOADING, TaskStatus.FAILED, TaskStatus.READY],
        [TaskStatus.FETCHING_INFO, TaskStatus.FAILED, TaskStatus.FETCHING_INFO],
    ],
)
def test_allowed_task_paths(path):
    for current, new in itertools.pairwise(path):
        assert check_transition(current, new) is new


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (TaskStatus.FETCHING_INFO, TaskStatus.DOWNLOADING),  # sans métadonnées
        (TaskStatus.READY, TaskStatus.PROCESSING),  # sans source
        (TaskStatus.COMPLETED, TaskStatus.CANCELLED),
        (TaskStatus.COMPLETED, TaskStatus.FAILED),
        (SegmentStatus.DONE, SegmentStatus.PENDING),
        (SegmentStatus.PENDING, SegmentStatus.DONE),
    ],
)
def test_forbidden_transitions(current, new):
    with pytest.raises(InvalidStateTransitionError):
        check_transition(current, new)


@pytest.mark.parametrize(
    ("mode", "video", "audio"),
    [
        (OutputMode.AUDIO_VIDEO, True, True),
        (OutputMode.VIDEO_ONLY, True, False),
        (OutputMode.AUDIO_ONLY, False, True),
    ],
)
def test_output_mode_needs(mode, video, audio):
    assert (mode.needs_video, mode.needs_audio) == (video, audio)


def test_source_files_cover_modes():
    video_only = SourceFiles(video_path=Path("v.webm"))
    both = SourceFiles(video_path=Path("v.webm"), audio_path=Path("a.m4a"))
    assert video_only.covers(OutputMode.VIDEO_ONLY)
    assert not video_only.covers(OutputMode.AUDIO_VIDEO)
    assert not video_only.covers(OutputMode.AUDIO_ONLY)
    assert all(both.covers(mode) for mode in OutputMode)


def test_video_task_defaults_and_counts():
    task = VideoTask(url="https://www.youtube.com/watch?v=jNQXAC9IVRw", mode=OutputMode.AUDIO_VIDEO)
    assert task.status is TaskStatus.FETCHING_INFO
    assert task.title == task.url
    task.segments = [
        Segment(number=1, start_s=0, end_s=5, mode=task.mode, status=SegmentStatus.DONE),
        Segment(number=2, start_s=5, end_s=9, mode=task.mode),
    ]
    assert task.count(SegmentStatus.DONE) == 1
    assert task.count(SegmentStatus.PENDING) == 1
    assert task.segments[1].duration_s == 4

    task.info = VideoInfo("jNQXAC9IVRw", task.url, "Me at the zoo", 19, True, True)
    assert task.title == "Me at the zoo"


def test_ids_are_unique():
    a = VideoTask(url="u", mode=OutputMode.AUDIO_ONLY)
    b = VideoTask(url="u", mode=OutputMode.AUDIO_ONLY)
    assert a.id != b.id
