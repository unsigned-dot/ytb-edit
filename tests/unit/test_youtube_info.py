"""Métadonnées et erreurs YouTube, sans réseau : yt-dlp est remplacé par un faux."""

import pytest
from yt_dlp.utils import DownloadError

from ytb_edit.core.errors import (
    NetworkError,
    UnsupportedVideoError,
    VideoUnavailableError,
    YouTubeError,
)
from ytb_edit.services import youtube
from ytb_edit.services.youtube import (
    fetch_video_info,
    translate_ytdlp_error,
    video_info_from_ytdlp,
)

ID = "jNQXAC9IVRw"

FORMATS = [
    {"format_id": "sb0", "vcodec": "none", "acodec": "none", "ext": "mhtml"},  # storyboard
    {"format_id": "140", "vcodec": "none", "acodec": "mp4a.40.2", "filesize": 300_000},
    {"format_id": "251", "vcodec": "none", "acodec": "opus", "filesize_approx": 350_000},
    {"format_id": "137", "vcodec": "avc1.640028", "acodec": "none", "filesize": 5_000_000},
    {"format_id": "399", "vcodec": "av01.0.08M.08", "acodec": "none", "filesize": 4_000_000},
    {"format_id": "18", "vcodec": "avc1.42001E", "acodec": "mp4a.40.2", "filesize": 900_000},
]


def make_raw(**overrides):
    raw = {
        "id": ID,
        "title": "Me at the zoo",
        "duration": 19,
        "uploader": "jawed",
        "live_status": "not_live",
        "availability": "public",
        "formats": FORMATS,
    }
    return raw | overrides


def test_video_info_nominal():
    info = video_info_from_ytdlp(make_raw())
    assert info.video_id == ID
    assert info.url == f"https://www.youtube.com/watch?v={ID}"
    assert info.title == "Me at the zoo"
    assert info.duration_s == 19
    assert info.has_video and info.has_audio
    assert info.uploader == "jawed"
    # plus grande piste vidéo + plus grande piste audio seule
    assert info.estimated_size == 5_000_000 + 350_000


def test_duration_is_rounded_up():
    assert video_info_from_ytdlp(make_raw(duration=19.2)).duration_s == 20


def test_video_without_audio():
    formats = [f for f in FORMATS if f["format_id"] in ("137", "399")]
    info = video_info_from_ytdlp(make_raw(formats=formats))
    assert info.has_video and not info.has_audio


def test_missing_title_falls_back_to_id():
    assert video_info_from_ytdlp(make_raw(title=None)).title == ID


def test_unknown_sizes_give_none():
    formats = [{"format_id": "18", "vcodec": "avc1", "acodec": "mp4a"}]
    assert video_info_from_ytdlp(make_raw(formats=formats)).estimated_size is None


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"live_status": "is_live"}, UnsupportedVideoError),
        ({"live_status": "is_upcoming"}, UnsupportedVideoError),
        ({"live_status": "post_live"}, UnsupportedVideoError),
        ({"availability": "private"}, VideoUnavailableError),
        ({"availability": "subscriber_only"}, UnsupportedVideoError),
        ({"availability": "needs_auth"}, UnsupportedVideoError),
        ({"availability": "premium_only"}, UnsupportedVideoError),
        ({"duration": None}, UnsupportedVideoError),
        ({"formats": []}, YouTubeError),
        ({"formats": [FORMATS[0]]}, YouTubeError),  # uniquement un storyboard
        ({"formats": [{**f, "has_drm": True} for f in FORMATS]}, UnsupportedVideoError),
    ],
)
def test_rejected_videos(overrides, error):
    with pytest.raises(error):
        video_info_from_ytdlp(make_raw(**overrides))


def test_drm_formats_are_ignored_when_others_exist():
    formats = [{**FORMATS[3], "has_drm": True}, FORMATS[1]]
    info = video_info_from_ytdlp(make_raw(formats=formats))
    assert not info.has_video and info.has_audio


def test_was_live_and_unlisted_are_accepted():
    info = video_info_from_ytdlp(make_raw(live_status="was_live", availability="unlisted"))
    assert info.duration_s == 19


# --- Erreurs yt-dlp ---------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "error"),
    [
        (
            f"ERROR: [youtube] {ID}: Private video. Sign in if you've been granted access",
            VideoUnavailableError,
        ),
        (f"ERROR: [youtube] {ID}: Video unavailable", VideoUnavailableError),
        (
            f"ERROR: [youtube] {ID}: Video unavailable. "
            "This video has been removed by the uploader",
            VideoUnavailableError,
        ),
        (
            f"ERROR: [youtube] {ID}: Video unavailable. This video is no longer available because "
            "the YouTube account associated with this video has been terminated.",
            VideoUnavailableError,
        ),
        (
            f"ERROR: [youtube] {ID}: Sign in to confirm your age. This video may be inappropriate "
            "for some users.",
            UnsupportedVideoError,
        ),
        (
            f"ERROR: [youtube] {ID}: Join this channel to get access to members-only content",
            UnsupportedVideoError,
        ),
        (f"ERROR: [youtube] {ID}: This video is DRM protected", UnsupportedVideoError),
        (f"ERROR: [youtube] {ID}: This live event will begin in 3 hours.", UnsupportedVideoError),
        (f"ERROR: [youtube] {ID}: Premieres in 2 days", UnsupportedVideoError),
        (
            f"ERROR: [youtube] {ID}: The uploader has not made "
            "this video available in your country",
            UnsupportedVideoError,
        ),
        (f"ERROR: [youtube] {ID}: Sign in to confirm you're not a bot.", YouTubeError),
        ("ERROR: unable to download video data: HTTP Error 429: Too Many Requests", NetworkError),
        # Message réel obtenu sans accès réseau :
        (
            f"ERROR: [youtube] {ID}: Unable to download API page: ('Unable to connect to proxy', "
            "OSError('Tunnel connection failed: 403 Forbidden'))",
            NetworkError,
        ),
        (
            "ERROR: Unable to download webpage: <urlopen error [Errno 11001] getaddrinfo failed>",
            NetworkError,
        ),
        ("ERROR: The read operation timed out", NetworkError),
        (f"ERROR: [youtube] {ID}: Requested format is not available", YouTubeError),
        ("ERROR: something completely unexpected", YouTubeError),
    ],
)
def test_translate_ytdlp_error(message, error):
    translated = translate_ytdlp_error(DownloadError(message))
    assert type(translated) is error
    assert translated.details == message
    assert translated.user_message


def test_drm_must_be_a_whole_word():
    # « drm » ne doit être détecté que comme mot entier
    assert type(translate_ytdlp_error(DownloadError("ERROR: hydrmoxy"))) is YouTubeError


# --- fetch_video_info avec un faux yt-dlp ------------------------------------


class FakeYDL:
    """Imite l'interface de yt_dlp.YoutubeDL utilisée par fetch_video_info."""

    result: dict | Exception = {}
    params: dict = {}

    def __init__(self, params):
        FakeYDL.params = params

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download):
        assert url == f"https://www.youtube.com/watch?v={ID}"
        assert download is False
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_fetch_video_info_success(monkeypatch):
    monkeypatch.setattr(youtube, "find_js_runtime", lambda: ("deno", "/bin/deno"))
    FakeYDL.result = make_raw()
    info = fetch_video_info(ID, ydl_class=FakeYDL)
    assert info.title == "Me at the zoo"
    assert FakeYDL.params["noplaylist"] is True
    assert FakeYDL.params["skip_download"] is True
    assert FakeYDL.params["js_runtimes"] == {"deno": {"path": "/bin/deno"}}
    assert "cookiefile" not in FakeYDL.params


def test_fetch_video_info_without_js_runtime(monkeypatch):
    monkeypatch.setattr(youtube, "find_js_runtime", lambda: None)
    FakeYDL.result = make_raw()
    fetch_video_info(ID, ydl_class=FakeYDL)
    assert "js_runtimes" not in FakeYDL.params  # yt-dlp garde son défaut


def test_fetch_video_info_translates_errors():
    FakeYDL.result = DownloadError(f"ERROR: [youtube] {ID}: Video unavailable")
    with pytest.raises(VideoUnavailableError) as exc:
        fetch_video_info(ID, ydl_class=FakeYDL)
    assert isinstance(exc.value.__cause__, DownloadError)


def test_find_js_runtime_prefers_deno(monkeypatch):
    available = {"node": "/usr/bin/node", "deno": "/usr/bin/deno"}
    monkeypatch.setattr(youtube.shutil, "which", available.get)
    assert youtube.find_js_runtime() == ("deno", "/usr/bin/deno")
    del available["deno"]
    assert youtube.find_js_runtime() == ("node", "/usr/bin/node")
    available.clear()
    assert youtube.find_js_runtime() is None
