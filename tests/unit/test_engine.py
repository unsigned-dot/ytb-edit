"""Moteur de file avec de faux services : aucun réseau, aucun FFmpeg."""

import threading
import time
from pathlib import Path

import pytest

from ytb_edit.core.engine import Engine, EngineConfig
from ytb_edit.core.errors import (
    FFmpegError,
    InvalidSegmentError,
    InvalidUrlError,
    MissingStreamError,
    NetworkError,
    OperationCancelled,
    VideoUnavailableError,
)
from ytb_edit.core.events import Notice, QueueIdle, TaskChanged, TaskRemoved
from ytb_edit.core.models import (
    OutputMode,
    SegmentStatus,
    SourceFiles,
    TaskStatus,
    VideoInfo,
)
from ytb_edit.services.cache import SourceCache

ID_A, ID_B = "aaaaaaaaaaa", "bbbbbbbbbbb"


def url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def make_info(video_id: str, title: str, *, duration: int = 600, audio: bool = True) -> VideoInfo:
    return VideoInfo(video_id, url(video_id), title, duration, True, audio, estimated_size=1000)


class FakeMedia:
    def __init__(self) -> None:
        self.infos: dict[str, VideoInfo | Exception] = {}
        self.download_gate = threading.Event()
        self.download_gate.set()
        self.download_error: Exception | None = None
        self.cut_errors: dict[int, Exception] = {}  # par début de segment
        self.downloads: list[tuple[str, bool, bool]] = []
        self.cuts: list[tuple[int, int, OutputMode]] = []

    def fetch_info(self, video_id):
        result = self.infos[video_id]
        if isinstance(result, Exception):
            raise result
        return result

    def download(
        self, info, dest_dir, *, want_video, want_audio, prefer_aac, is_cancelled, on_progress
    ):
        self.downloads.append((info.video_id, want_video, want_audio))
        while not self.download_gate.wait(0.02):
            if is_cancelled():
                raise OperationCancelled()
        if self.download_error:
            raise self.download_error
        on_progress(0.5, "Téléchargement")
        dest_dir.mkdir(parents=True, exist_ok=True)
        video = audio = None
        if want_video:
            video = dest_dir / "137.webm"
            video.write_bytes(b"video")
        if want_audio:
            audio = dest_dir / "140.m4a"
            audio.write_bytes(b"audio")
        return SourceFiles(video, audio)

    def validate_source(self, source, info):
        pass

    def output_container(self, source, mode, audio_format):
        return "mp4" if mode.needs_video else "m4a"

    def cut(self, request, *, is_cancelled, on_progress):
        if error := self.cut_errors.get(request.start_s):
            raise error
        self.cuts.append((request.start_s, request.end_s, request.mode))
        request.output.write_bytes(b"clip")
        return float(request.start_s)


@pytest.fixture
def env(tmp_path):
    media = FakeMedia()
    media.infos = {ID_A: make_info(ID_A, "Vidéo A"), ID_B: make_info(ID_B, "Vidéo B")}
    events: list = []
    cache = SourceCache(tmp_path / "cache")
    output = tmp_path / "clips"
    engine = Engine(media, cache, events.append, EngineConfig(output_dir=output))
    engine.start_workers()
    yield engine, media, events, output, cache
    engine.shutdown(timeout=2)


def wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Condition non atteinte à temps")


def task_of(engine: Engine, task_id: str):
    return next(t for t in engine.snapshot() if t.id == task_id)


def status_is(engine, task_id, status):
    return lambda: task_of(engine, task_id).status is status


def add_ready_video(engine, video_id, mode=OutputMode.AUDIO_VIDEO):
    task_id, _ = engine.add_video(url(video_id), mode)
    wait_for(status_is(engine, task_id, TaskStatus.READY))
    return task_id


def test_full_pipeline_creates_named_clips(env):
    engine, media, events, output, _ = env
    task_id = add_ready_video(engine, ID_A)
    engine.add_segment(task_id, 200, 230)
    engine.add_segment(task_id, 310, 315)
    engine.start()
    wait_for(status_is(engine, task_id, TaskStatus.COMPLETED))

    task = task_of(engine, task_id)
    assert [s.status for s in task.segments] == [SegmentStatus.DONE] * 2
    assert sorted(p.name for p in (output / "Vidéo A").iterdir()) == [
        "clip_001_03m20s-03m50s.mp4",
        "clip_002_05m10s-05m15s.mp4",
    ]
    assert len(media.downloads) == 1
    wait_for(lambda: any(isinstance(e, QueueIdle) for e in events))
    summary = next(e for e in events if isinstance(e, QueueIdle)).summary
    assert (summary.videos, summary.clips, summary.errors) == (1, 2, 0)


def test_nothing_is_downloaded_while_queue_is_paused(env):
    engine, media, *_ = env
    task_id = add_ready_video(engine, ID_A)
    engine.add_segment(task_id, 0, 10)
    time.sleep(0.2)
    assert media.downloads == []
    assert task_of(engine, task_id).status is TaskStatus.READY


def test_one_failing_video_does_not_stop_the_others(env):
    engine, media, events, *_ = env
    media.infos[ID_A] = VideoUnavailableError("Vidéo indisponible.")
    bad, _ = engine.add_video(url(ID_A), OutputMode.AUDIO_VIDEO)
    good = add_ready_video(engine, ID_B)
    engine.add_segment(good, 0, 10)
    engine.start()
    wait_for(status_is(engine, good, TaskStatus.COMPLETED))
    failed = task_of(engine, bad)
    assert failed.status is TaskStatus.FAILED
    assert failed.error == "Vidéo indisponible."
    assert any(isinstance(e, Notice) and e.error for e in events)


def test_download_failure_then_retry(env):
    engine, media, *_ = env
    media.download_error = NetworkError("Problème de connexion réseau.")
    task_id = add_ready_video(engine, ID_A)
    engine.add_segment(task_id, 0, 10)
    engine.start()
    wait_for(status_is(engine, task_id, TaskStatus.FAILED))
    assert task_of(engine, task_id).error == "Problème de connexion réseau."

    media.download_error = None
    engine.retry_task(task_id)
    wait_for(status_is(engine, task_id, TaskStatus.COMPLETED))


def test_segment_added_during_download_is_processed_without_new_download(env):
    engine, media, *_ = env
    media.download_gate.clear()
    task_id = add_ready_video(engine, ID_A)
    engine.add_segment(task_id, 0, 10)
    engine.start()
    wait_for(status_is(engine, task_id, TaskStatus.DOWNLOADING))
    engine.add_segment(task_id, 100, 120)  # pendant le téléchargement
    media.download_gate.set()
    wait_for(status_is(engine, task_id, TaskStatus.COMPLETED))
    assert len(media.downloads) == 1
    assert [c[:2] for c in media.cuts] == [(0, 10), (100, 120)]


def test_segment_added_after_completion_reuses_source(env):
    engine, media, *_ = env
    task_id = add_ready_video(engine, ID_A)
    engine.add_segment(task_id, 0, 10)
    engine.start()
    wait_for(status_is(engine, task_id, TaskStatus.COMPLETED))
    engine.add_segment(task_id, 20, 30)
    wait_for(lambda: task_of(engine, task_id).count(SegmentStatus.DONE) == 2)
    wait_for(status_is(engine, task_id, TaskStatus.COMPLETED))
    assert len(media.downloads) == 1
    assert task_of(engine, task_id).segments[1].number == 2


def test_source_in_cache_from_previous_session_is_reused(env):
    engine, media, _events, _output, cache = env
    directory = cache.dir_for(ID_A)
    directory.mkdir(parents=True)
    (directory / "137.webm").write_bytes(b"v")
    (directory / "140.m4a").write_bytes(b"a")
    cache.save(ID_A, SourceFiles(directory / "137.webm", directory / "140.m4a"))

    task_id = add_ready_video(engine, ID_A)
    engine.add_segment(task_id, 0, 10)
    engine.start()
    wait_for(status_is(engine, task_id, TaskStatus.COMPLETED))
    assert media.downloads == []


def test_mode_change_downloads_only_missing_stream(env):
    engine, media, *_ = env
    task_id = add_ready_video(engine, ID_A, OutputMode.AUDIO_ONLY)
    engine.add_segment(task_id, 0, 10)
    engine.start()
    wait_for(status_is(engine, task_id, TaskStatus.COMPLETED))
    engine.set_mode(task_id, OutputMode.AUDIO_VIDEO)
    engine.add_segment(task_id, 20, 30)
    wait_for(lambda: task_of(engine, task_id).count(SegmentStatus.DONE) == 2)
    assert media.downloads == [(ID_A, False, True), (ID_A, True, False)]
    assert [c[2] for c in media.cuts] == [OutputMode.AUDIO_ONLY, OutputMode.AUDIO_VIDEO]


def test_failed_segment_does_not_fail_the_video(env):
    engine, media, events, *_ = env
    media.cut_errors[0] = FFmpegError("Échec de FFmpeg pendant la découpe (voir les logs).")
    task_id = add_ready_video(engine, ID_A)
    engine.add_segment(task_id, 0, 10)
    engine.add_segment(task_id, 20, 30)
    engine.start()
    wait_for(status_is(engine, task_id, TaskStatus.COMPLETED))
    statuses = [s.status for s in task_of(engine, task_id).segments]
    assert statuses == [SegmentStatus.FAILED, SegmentStatus.DONE]
    wait_for(lambda: any(isinstance(e, QueueIdle) for e in events))
    summary = next(e for e in events if isinstance(e, QueueIdle)).summary
    assert summary.errors == 1

    media.cut_errors.clear()
    engine.retry_task(task_id)
    wait_for(lambda: task_of(engine, task_id).count(SegmentStatus.DONE) == 2)


def test_cancel_during_download(env):
    engine, media, *_ = env
    media.download_gate.clear()
    task_id = add_ready_video(engine, ID_A)
    engine.add_segment(task_id, 0, 10)
    engine.start()
    wait_for(status_is(engine, task_id, TaskStatus.DOWNLOADING))
    engine.cancel_task(task_id)
    wait_for(lambda: not engine.is_busy())
    task = task_of(engine, task_id)
    assert task.status is TaskStatus.CANCELLED
    assert task.segments[0].status is SegmentStatus.CANCELLED


def test_existing_clip_is_never_overwritten(env):
    engine, _media, _events, output, _ = env
    folder = output / "Vidéo A"
    folder.mkdir(parents=True)
    (folder / "clip_001_00m00s-00m10s.mp4").write_bytes(b"ancien")
    task_id = add_ready_video(engine, ID_A)
    engine.add_segment(task_id, 0, 10)
    engine.start()
    wait_for(status_is(engine, task_id, TaskStatus.COMPLETED))
    assert (folder / "clip_001_00m00s-00m10s.mp4").read_bytes() == b"ancien"
    assert (folder / "clip_001_00m00s-00m10s_1.mp4").read_bytes() == b"clip"


def test_duplicate_url_returns_existing_task(env):
    engine, *_ = env
    first, new1 = engine.add_video(url(ID_A), OutputMode.AUDIO_VIDEO)
    second, new2 = engine.add_video(f"https://youtu.be/{ID_A}?t=5", OutputMode.AUDIO_ONLY)
    assert (first, new1, new2) == (second, True, False)


def test_invalid_url_is_rejected_immediately(env):
    engine, *_ = env
    with pytest.raises(InvalidUrlError):
        engine.add_video("https://example.com/video", OutputMode.AUDIO_VIDEO)
    assert engine.snapshot() == []


def test_mode_is_adjusted_for_video_without_audio(env):
    engine, media, *_ = env
    media.infos[ID_A] = make_info(ID_A, "Muet", audio=False)
    task_id = add_ready_video(engine, ID_A, OutputMode.AUDIO_VIDEO)
    assert task_of(engine, task_id).mode is OutputMode.VIDEO_ONLY
    with pytest.raises(MissingStreamError):
        engine.set_mode(task_id, OutputMode.AUDIO_ONLY)


def test_invalid_segments_are_rejected(env):
    engine, *_ = env
    task_id = add_ready_video(engine, ID_A)
    for start, end in [(30, 30), (50, 10), (590, 601), (-1, 5)]:
        with pytest.raises(InvalidSegmentError):
            engine.add_segment(task_id, start, end)
    assert task_of(engine, task_id).segments == []


def test_remove_task_deletes_cache_and_keeps_clips(env):
    engine, _media, events, output, cache = env
    task_id = add_ready_video(engine, ID_A)
    engine.add_segment(task_id, 0, 10)
    engine.start()
    wait_for(status_is(engine, task_id, TaskStatus.COMPLETED))
    assert cache.load(ID_A) is not None
    engine.remove_task(task_id)
    assert cache.load(ID_A) is None
    assert not cache.dir_for(ID_A).exists()
    assert any(isinstance(e, TaskRemoved) for e in events)
    assert (output / "Vidéo A" / "clip_001_00m00s-00m10s.mp4").exists()


def test_shutdown_cleans_cache_unless_asked_to_keep(tmp_path):
    for keep in (False, True):
        media = FakeMedia()
        media.infos = {ID_A: make_info(ID_A, "Vidéo A")}
        cache = SourceCache(tmp_path / f"cache-{keep}")
        engine = Engine(
            media,
            cache,
            lambda e: None,
            EngineConfig(output_dir=tmp_path / "out", keep_cache_on_exit=keep),
        )
        engine.start_workers()
        task_id = add_ready_video(engine, ID_A)
        engine.add_segment(task_id, 0, 10)
        engine.start()
        wait_for(status_is(engine, task_id, TaskStatus.COMPLETED))
        engine.shutdown(timeout=2)
        assert (cache.load(ID_A) is not None) is keep


def test_cache_limit_evicts_oldest_completed_source(env):
    engine, media, _events, _output, cache = env
    engine.configure(cache_limit_bytes=12)  # chaque source fait 10 octets
    first = add_ready_video(engine, ID_A)
    engine.add_segment(first, 0, 10)
    engine.start()
    wait_for(status_is(engine, first, TaskStatus.COMPLETED))
    second = add_ready_video(engine, ID_B)
    engine.add_segment(second, 0, 10)
    wait_for(status_is(engine, second, TaskStatus.COMPLETED))
    assert cache.load(ID_A) is None
    assert cache.load(ID_B) is not None
    # Un nouveau segment sur la vidéo purgée déclenche un nouveau téléchargement.
    engine.add_segment(first, 20, 30)
    wait_for(lambda: task_of(engine, first).count(SegmentStatus.DONE) == 2)
    assert [d[0] for d in media.downloads] == [ID_A, ID_B, ID_A]


def test_events_carry_copies(env):
    engine, _media, events, *_ = env
    task_id = add_ready_video(engine, ID_A)
    snapshot = next(e.task for e in events if isinstance(e, TaskChanged))
    snapshot.segments.append("intrus")  # type: ignore[arg-type]
    assert task_of(engine, task_id).segments == []


def test_without_output_dir_segments_fail_clearly(tmp_path):
    media = FakeMedia()
    media.infos = {ID_A: make_info(ID_A, "Vidéo A")}
    engine = Engine(media, SourceCache(tmp_path / "c"), lambda e: None, EngineConfig())
    engine.start_workers()
    try:
        task_id = add_ready_video(engine, ID_A)
        engine.add_segment(task_id, 0, 10)
        engine.start()
        wait_for(status_is(engine, task_id, TaskStatus.COMPLETED))
        assert task_of(engine, task_id).segments[0].error == "Aucun dossier de sortie choisi."
    finally:
        engine.shutdown(timeout=2)


def test_output_paths_are_recorded(env):
    engine, _media, _events, output, _ = env
    task_id = add_ready_video(engine, ID_A)
    engine.add_segment(task_id, 0, 10)
    engine.start()
    wait_for(status_is(engine, task_id, TaskStatus.COMPLETED))
    segment = task_of(engine, task_id).segments[0]
    assert segment.output_path == output / "Vidéo A" / "clip_001_00m00s-00m10s.mp4"
    assert isinstance(segment.output_path, Path)
    assert segment.actual_start_s == 0
