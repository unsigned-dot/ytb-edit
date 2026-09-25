"""Tests contre le vrai YouTube. Désactivés par défaut : ``pytest -m network``.

Vidéo utilisée : « Me at the zoo » (19 s, publique, première vidéo de YouTube),
également utilisée par la suite de tests de yt-dlp.
"""

import pytest

from ytb_edit.core.errors import InvalidUrlError, VideoUnavailableError
from ytb_edit.services.youtube import fetch_video_info, find_js_runtime, parse_video_id

pytestmark = pytest.mark.network

TEST_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def test_js_runtime_installed():
    assert find_js_runtime() is not None, "Installer Deno : winget install DenoLand.Deno"


def test_fetch_real_metadata():
    info = fetch_video_info(parse_video_id(TEST_URL))
    assert info.title == "Me at the zoo"
    assert 18 <= info.duration_s <= 20
    assert info.has_video and info.has_audio


def test_nonexistent_video():
    with pytest.raises((VideoUnavailableError, InvalidUrlError)):
        fetch_video_info("aaaaaaaaaaa")
