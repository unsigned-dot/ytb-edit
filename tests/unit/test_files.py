from collections import namedtuple
from pathlib import Path

import pytest

from ytb_edit.core.errors import DiskSpaceError
from ytb_edit.services import files
from ytb_edit.services.files import (
    clip_filename,
    ensure_free_space,
    sanitize_filename,
    unique_path,
    video_output_dir,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Ma vidéo", "Ma vidéo"),
        ('AC/DC: "Live" <2024> | best?*', "AC_DC_ _Live_ _2024_ _ best__"),
        ("Titre avec point final.", "Titre avec point final"),
        ("  espaces   multiples \t et\nretours  ", "espaces multiples et retours"),
        ("CON", "CON_"),
        ("com1", "com1_"),
        ("LPT9.txt", "LPT9.txt_"),
        ("CONSOLE", "CONSOLE"),
        ("Cafe\u0301", "Café"),  # normalisation NFC
        ("emoji 🎬 ok", "emoji 🎬 ok"),
    ],
)
def test_sanitize_filename(name, expected):
    assert sanitize_filename(name) == expected


@pytest.mark.parametrize("name", ["", "   ", "...", "???", "\x00\x01"])
def test_sanitize_filename_uses_fallback(name):
    assert sanitize_filename(name, fallback="dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_sanitize_filename_truncates():
    assert len(sanitize_filename("x" * 300)) == files.MAX_NAME_LENGTH


def test_video_output_dir_respects_max_path():
    root = Path("C:/Users/Moi/" + "d" * 150)
    directory = video_output_dir(root, "T" * 200, "abc")
    assert len(str(directory)) + 1 + files.CLIP_NAME_RESERVE <= files.MAX_PATH_LENGTH


@pytest.mark.parametrize(
    ("number", "start", "end", "hours", "ext", "expected"),
    [
        (1, 200, 230, False, "mp4", "clip_001_03m20s-03m50s.mp4"),
        (12, 310, 315, False, ".m4a", "clip_012_05m10s-05m15s.m4a"),
        (4, 3723, 3780, True, "mp4", "clip_004_1h02m03s-1h03m00s.mp4"),
        (5, 200, 230, True, "mp3", "clip_005_0h03m20s-0h03m50s.mp3"),
    ],
)
def test_clip_filename(number, start, end, hours, ext, expected):
    assert clip_filename(number, start, end, with_hours=hours, ext=ext) == expected


def test_unique_path(tmp_path):
    target = tmp_path / "clip_001.mp4"
    assert unique_path(target) == target
    target.write_bytes(b"")
    assert unique_path(target).name == "clip_001_1.mp4"
    (tmp_path / "clip_001_1.mp4").write_bytes(b"")
    assert unique_path(target).name == "clip_001_2.mp4"


def test_ensure_free_space(monkeypatch, tmp_path):
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(files.shutil, "disk_usage", lambda p: usage(100, 90, 10 * 1024**2))
    ensure_free_space(tmp_path / "pas" / "encore" / "cree", 5 * 1024**2)
    with pytest.raises(DiskSpaceError) as exc:
        ensure_free_space(tmp_path, 3 * 1024**3)
    assert "3 Go" in exc.value.user_message
    assert "10 Mo" in exc.value.user_message
