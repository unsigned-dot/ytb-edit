"""Téléchargement avec un faux yt-dlp : sélection des formats, fichiers, progression."""

import pytest
from yt_dlp.utils import DownloadCancelled, DownloadError

from ytb_edit.core.errors import (
    DiskSpaceError,
    MissingStreamError,
    OperationCancelled,
    SourceCorruptedError,
)
from ytb_edit.core.models import VideoInfo
from ytb_edit.services import youtube
from ytb_edit.services.youtube import download_streams

INFO = VideoInfo(
    "jNQXAC9IVRw",
    "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    "Zoo",
    19,
    True,
    True,
    estimated_size=1000,
)


class FakeDownloadYDL:
    """Crée les fichiers annoncés et appelle les hooks comme yt-dlp."""

    downloads: list[dict] = []
    error: Exception | None = None
    params: dict = {}

    def __init__(self, params):
        FakeDownloadYDL.params = params

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download):
        assert download is True
        template = self.params["outtmpl"]["default"]
        result = []
        for fmt in self.downloads:
            path = template.replace("%(format_id)s", fmt["format_id"]).replace(
                "%(ext)s", fmt["ext"]
            )
            for hook in self.params["progress_hooks"]:
                hook(
                    {
                        "status": "downloading",
                        "filename": path,
                        "downloaded_bytes": 100,
                        "total_bytes": fmt["size"],
                        "speed": 2_097_152,
                        "eta": 65,
                        "info_dict": fmt,
                    }
                )
            if self.error:
                raise self.error
            with open(path, "wb") as f:
                f.write(b"x" * fmt["size"])
            for hook in self.params["progress_hooks"]:
                hook(
                    {
                        "status": "finished",
                        "filename": path,
                        "downloaded_bytes": fmt["size"],
                        "info_dict": fmt,
                    }
                )
            result.append({**fmt, "filepath": path})
        return {"id": INFO.video_id, "requested_downloads": result}


AUDIO = {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2", "size": 200}
VIDEO = {"format_id": "399", "ext": "mp4", "vcodec": "av01", "acodec": "none", "size": 800}
COMBINED = {"format_id": "18", "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a", "size": 500}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(youtube, "find_js_runtime", lambda: None)
    FakeDownloadYDL.downloads = [AUDIO, VIDEO]
    FakeDownloadYDL.error = None


def test_downloads_separate_streams(tmp_path):
    progress = []
    source = download_streams(
        INFO,
        tmp_path,
        want_video=True,
        want_audio=True,
        on_progress=lambda f, t: progress.append((f, t)),
        ydl_class=FakeDownloadYDL,
    )
    assert source.video_path == tmp_path / "399.mp4"
    assert source.audio_path == tmp_path / "140.m4a"
    params = FakeDownloadYDL.params
    assert params["format"] == "ba/b,bv/b"  # audio d'abord
    assert params["fixup"] == "never" and params["noplaylist"] is True
    fractions = [f for f, _ in progress]
    assert fractions == sorted(fractions) and fractions[-1] >= 0.99
    assert any("Mo/s" in t and "reste 1:05" in t for _, t in progress)


def test_audio_only_prefers_aac(tmp_path):
    FakeDownloadYDL.downloads = [AUDIO]
    source = download_streams(
        INFO,
        tmp_path,
        want_video=False,
        want_audio=True,
        prefer_aac=True,
        ydl_class=FakeDownloadYDL,
    )
    assert FakeDownloadYDL.params["format"] == "ba[acodec^=mp4a]/ba/b"
    assert source.video_path is None and source.audio_path is not None


def test_combined_fallback_serves_both_streams(tmp_path):
    FakeDownloadYDL.downloads = [COMBINED]
    source = download_streams(
        INFO, tmp_path, want_video=True, want_audio=True, ydl_class=FakeDownloadYDL
    )
    assert source.video_path == source.audio_path == tmp_path / "18.mp4"


def test_missing_audio_stream(tmp_path):
    FakeDownloadYDL.downloads = [VIDEO]
    with pytest.raises(MissingStreamError):
        download_streams(
            INFO, tmp_path, want_video=True, want_audio=True, ydl_class=FakeDownloadYDL
        )


def test_empty_file_is_reported_as_corrupted(tmp_path):
    FakeDownloadYDL.downloads = [{**AUDIO, "size": 0}]
    with pytest.raises(SourceCorruptedError):
        download_streams(
            INFO, tmp_path, want_video=False, want_audio=True, ydl_class=FakeDownloadYDL
        )


def test_cancellation_from_hook(tmp_path):
    with pytest.raises(OperationCancelled):
        download_streams(
            INFO,
            tmp_path,
            want_video=True,
            want_audio=True,
            is_cancelled=lambda: True,
            ydl_class=FakeDownloadYDL,
        )


def test_cancellation_wrapped_by_ytdlp(tmp_path):
    FakeDownloadYDL.error = DownloadCancelled("stop")
    with pytest.raises(OperationCancelled):
        download_streams(
            INFO, tmp_path, want_video=True, want_audio=True, ydl_class=FakeDownloadYDL
        )


def test_disk_full_is_translated(tmp_path):
    FakeDownloadYDL.error = DownloadError(
        "ERROR: unable to write data: [Errno 28] No space left on device"
    )
    with pytest.raises(DiskSpaceError):
        download_streams(
            INFO, tmp_path, want_video=True, want_audio=True, ydl_class=FakeDownloadYDL
        )
