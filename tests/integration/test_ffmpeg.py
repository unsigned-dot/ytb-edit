"""Découpe réelle avec FFmpeg sur des sources générées localement (pas de réseau).

Les sources imitent YouTube : vidéo seule (VP9/webm et H.264/mp4 avec images B),
audio seul (Opus/webm et AAC/m4a), une image clé toutes les 2 s.
"""

import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from ytb_edit.core.engine import CutRequest
from ytb_edit.core.errors import FFmpegError, OperationCancelled, SourceCorruptedError
from ytb_edit.core.models import AudioFormat, OutputMode, SourceFiles, VideoInfo
from ytb_edit.services import process
from ytb_edit.services.ffmpeg import CutPlan, FFmpeg, find_tools
from ytb_edit.services.media import YouTubeFFmpegMedia

pytestmark = pytest.mark.ffmpeg

TOOLS = find_tools()
if TOOLS is None:
    pytest.skip("FFmpeg absent", allow_module_level=True)

DURATION = 30


def _encode(args: list[str]) -> None:
    subprocess.run([TOOLS.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def _has_encoder(name: str) -> bool:
    out = subprocess.run(
        [TOOLS.ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True
    ).stdout
    return f" {name} " in out


@pytest.fixture(scope="module")
def sources(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("sources")
    lavfi_video = ["-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=30:duration={DURATION}"]
    lavfi_audio = ["-f", "lavfi", "-i", f"sine=frequency=440:duration={DURATION}"]
    files = {}
    _encode(
        [
            *lavfi_video,
            "-c:v",
            "libx264",
            "-g",
            "60",
            "-keyint_min",
            "60",
            "-sc_threshold",
            "0",
            "-bf",
            "2",
            "-an",
            str(d / "h264.mp4"),
        ]
    )
    files["h264"] = d / "h264.mp4"
    if _has_encoder("libvpx-vp9"):
        _encode(
            [
                *lavfi_video,
                "-c:v",
                "libvpx-vp9",
                "-deadline",
                "realtime",
                "-g",
                "60",
                "-an",
                str(d / "vp9.webm"),
            ]
        )
        files["vp9"] = d / "vp9.webm"
    _encode([*lavfi_audio, "-c:a", "aac", str(d / "aac.m4a")])
    files["aac"] = d / "aac.m4a"
    if _has_encoder("libopus"):
        _encode([*lavfi_audio, "-c:a", "libopus", str(d / "opus.webm")])
        files["opus"] = d / "opus.webm"
    return files


@pytest.fixture
def ffmpeg() -> FFmpeg:
    return FFmpeg(TOOLS)


def _streams(path: Path) -> dict[str, dict]:
    out = subprocess.run(
        [
            TOOLS.ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,start_time,duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    import json

    return {s["codec_type"]: s for s in json.loads(out)["streams"]}


def _video_audio_pairs(sources):
    videos = [k for k in ("vp9", "h264") if k in sources]
    audios = [k for k in ("opus", "aac") if k in sources]
    return [(v, a) for v in videos for a in audios]


def test_find_keyframe_before(ffmpeg, sources):
    video = sources["h264"]
    assert ffmpeg.find_keyframe_before(video, 13.0) == pytest.approx(12.0)
    assert ffmpeg.find_keyframe_before(video, 12.0) == pytest.approx(12.0)
    assert ffmpeg.find_keyframe_before(video, 1.0) == pytest.approx(0.0)


@pytest.mark.parametrize("keyframe", [0.0, 12.0, 24.0])
def test_audio_video_cut_is_synchronised(ffmpeg, sources, tmp_path, keyframe):
    for video_key, audio_key in _video_audio_pairs(sources):
        out = tmp_path / f"{video_key}-{audio_key}-{keyframe}.mp4"
        plan = CutPlan(
            out, keyframe, keyframe + 5, video=sources[video_key], audio=sources[audio_key]
        )
        ffmpeg.cut(plan, is_cancelled=lambda: False)
        streams = _streams(out)
        video, audio = streams["video"], streams["audio"]
        # vidéo et audio démarrent ensemble (au plus 0,1 s d'audio en tête)
        gap = float(video["start_time"]) - float(audio["start_time"])
        assert 0 <= gap <= 0.15, (video_key, audio_key, gap)
        # la vidéo commence sur l'image clé et couvre tout le segment demandé
        assert float(video["duration"]) == pytest.approx(5.0, abs=0.15), (video_key, audio_key)


def test_video_only_cut(ffmpeg, sources, tmp_path):
    out = tmp_path / "video.mp4"
    ffmpeg.cut(CutPlan(out, 12.0, 20.0, video=sources["h264"]), is_cancelled=lambda: False)
    streams = _streams(out)
    assert set(streams) == {"video"}
    assert float(streams["video"]["duration"]) == pytest.approx(8.0, abs=0.15)


@pytest.mark.parametrize(
    ("audio_key", "container", "codec"),
    [
        ("aac", "m4a", "aac"),
        ("opus", "opus", "opus"),
        ("opus", "mp3", "mp3"),
        ("aac", "mp3", "mp3"),
    ],
)
def test_audio_only_cut(ffmpeg, sources, tmp_path, audio_key, container, codec):
    if audio_key not in sources:
        pytest.skip("encodeur absent")
    if container == "mp3" and not _has_encoder("libmp3lame"):
        pytest.skip("libmp3lame absent")
    out = tmp_path / f"audio.{container}"
    ffmpeg.cut(
        CutPlan(out, 13.0, 20.0, audio=sources[audio_key], container=container),
        is_cancelled=lambda: False,
    )
    streams = _streams(out)
    assert set(streams) == {"audio"}
    assert streams["audio"]["codec_name"] == codec
    assert ffmpeg.probe(out).duration == pytest.approx(7.0, abs=0.15)


def test_progress_is_reported(ffmpeg, sources, tmp_path):
    values: list[float] = []
    ffmpeg.cut(
        CutPlan(tmp_path / "p.mp4", 0.0, 20.0, video=sources["h264"], audio=sources["aac"]),
        is_cancelled=lambda: False,
        on_progress=values.append,
    )
    assert values and max(values) == pytest.approx(1.0, abs=0.05)


def test_probe_rejects_corrupted_file(ffmpeg, tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"ceci n'est pas une video" * 100)
    with pytest.raises(FFmpegError):
        ffmpeg.probe(bad)


def test_process_can_be_cancelled(tmp_path):
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    start = time.monotonic()
    with pytest.raises(OperationCancelled):
        process.run(
            [
                TOOLS.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-re",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=duration=60",
                str(tmp_path / "long.mp4"),
            ],
            is_cancelled=cancel.is_set,
        )
    assert time.monotonic() - start < 3


# --- YouTubeFFmpegMedia (couche utilisée par le moteur) ------------------------


def _info(duration: int = DURATION) -> VideoInfo:
    return VideoInfo("aaaaaaaaaaa", "u", "Test", duration, True, True)


def test_media_validate_source(sources):
    media = YouTubeFFmpegMedia(FFmpeg(TOOLS))
    good = SourceFiles(sources["h264"], sources["aac"])
    media.validate_source(good, _info())
    with pytest.raises(SourceCorruptedError, match="incomplet"):
        media.validate_source(good, _info(duration=120))
    with pytest.raises(SourceCorruptedError):
        media.validate_source(SourceFiles(sources["aac"], None), _info())  # pas de vidéo


def test_media_output_container(sources):
    media = YouTubeFFmpegMedia(FFmpeg(TOOLS))
    both = SourceFiles(sources["h264"], sources["aac"])
    assert media.output_container(both, OutputMode.AUDIO_VIDEO, AudioFormat.M4A) == "mp4"
    assert media.output_container(both, OutputMode.AUDIO_ONLY, AudioFormat.M4A) == "m4a"
    assert media.output_container(both, OutputMode.AUDIO_ONLY, AudioFormat.MP3) == "mp3"
    if "opus" in sources:
        opus = SourceFiles(None, sources["opus"])
        assert media.output_container(opus, OutputMode.AUDIO_ONLY, AudioFormat.M4A) == "opus"


def test_media_cut_snaps_to_keyframe(sources, tmp_path):
    media = YouTubeFFmpegMedia(FFmpeg(TOOLS))
    out = tmp_path / "clip.mp4"
    request = CutRequest(
        SourceFiles(sources["h264"], sources["aac"]), OutputMode.AUDIO_VIDEO, 13, 18, out, "mp4"
    )
    actual = media.cut(request, is_cancelled=lambda: False, on_progress=lambda f: None)
    assert actual == pytest.approx(12.0)
    # 6 s de vidéo + au plus 0,1 s d'audio en tête et le remplissage d'une trame AAC
    assert FFmpeg(TOOLS).probe(out).duration == pytest.approx(6.0, abs=0.25)


def test_find_tools_with_custom_dir(tmp_path):
    ffmpeg_dir = Path(TOOLS.ffmpeg).parent
    assert find_tools(str(ffmpeg_dir)) is not None
    assert shutil.which("ffmpeg") is not None or find_tools(str(tmp_path)) is None


# --- Pipeline complet : moteur + vrai FFmpeg, seul YouTube est simulé ---------------


class LocalMedia(YouTubeFFmpegMedia):
    """Comme en production, mais « télécharge » en copiant des fichiers locaux."""

    def __init__(self, sources: dict[str, Path]) -> None:
        super().__init__(FFmpeg(TOOLS))
        self.sources = sources

    def fetch_info(self, video_id):
        return VideoInfo(
            video_id,
            f"https://www.youtube.com/watch?v={video_id}",
            'Ma vidéo : "test" 1/2',
            DURATION,
            True,
            True,
        )

    def download(
        self, info, dest_dir, *, want_video, want_audio, prefer_aac, is_cancelled, on_progress
    ):
        dest_dir.mkdir(parents=True, exist_ok=True)
        video = audio = None
        if want_video:
            video = dest_dir / "video.webm"
            shutil.copy(self.sources.get("vp9", self.sources["h264"]), video)
        if want_audio:
            audio = dest_dir / "audio.m4a"
            shutil.copy(self.sources["aac"], audio)
        on_progress(1.0, "Téléchargement")
        return SourceFiles(video, audio)


def test_full_pipeline_with_real_ffmpeg(sources, tmp_path):
    from ytb_edit.core.engine import Engine, EngineConfig
    from ytb_edit.core.models import SegmentStatus, TaskStatus
    from ytb_edit.services.cache import SourceCache

    output = tmp_path / "clips"
    engine = Engine(
        LocalMedia(sources),
        SourceCache(tmp_path / "cache"),
        lambda e: None,
        EngineConfig(output_dir=output),
    )
    engine.start_workers()
    try:
        task_id, _ = engine.add_video("https://youtu.be/aaaaaaaaaaa", OutputMode.AUDIO_VIDEO)
        deadline = time.monotonic() + 10
        while engine.snapshot()[0].status is not TaskStatus.READY:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        engine.add_segment(task_id, 13, 18)
        engine.add_segment(task_id, 25, 30)
        engine.start()
        deadline = time.monotonic() + 60
        while engine.snapshot()[0].status is not TaskStatus.COMPLETED:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        engine.set_mode(task_id, OutputMode.AUDIO_ONLY)
        engine.add_segment(task_id, 2, 9)
        deadline = time.monotonic() + 60
        while engine.snapshot()[0].count(SegmentStatus.DONE) < 3:
            assert time.monotonic() < deadline
            time.sleep(0.05)
    finally:
        engine.shutdown(timeout=5)

    folder = output / "Ma vidéo _ _test_ 1_2"
    names = sorted(p.name for p in folder.iterdir())
    assert names == [
        "clip_001_00m13s-00m18s.mp4",
        "clip_002_00m25s-00m30s.mp4",
        "clip_003_00m02s-00m09s.m4a",
    ]
    probe = FFmpeg(TOOLS).probe(folder / names[0])
    assert probe.has_video and probe.has_audio
    assert probe.duration == pytest.approx(6.0, abs=0.25)  # début réel : image clé à 12 s
    audio = FFmpeg(TOOLS).probe(folder / names[2])
    assert not audio.has_video and audio.audio_codec == "aac"
    assert audio.duration == pytest.approx(7.0, abs=0.15)
    assert not any(p.name.endswith(".part.mp4") for p in folder.iterdir())
