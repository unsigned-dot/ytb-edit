import pytest

from ytb_edit.core.errors import InvalidUrlError
from ytb_edit.services.youtube import canonical_url, parse_video_id

ID = "jNQXAC9IVRw"


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={ID}",
        f"http://youtube.com/watch?v={ID}",
        f"www.youtube.com/watch?v={ID}",
        f"youtube.com/watch?v={ID}",
        f"https://m.youtube.com/watch?v={ID}",
        f"https://music.youtube.com/watch?v={ID}",
        f"https://www.youtube.com/watch?v={ID}&t=42s",
        f"https://www.youtube.com/watch?v={ID}&list=PLabcdefghijkl&index=3",
        f"https://www.youtube.com/watch?feature=share&v={ID}",
        f"https://youtu.be/{ID}",
        f"https://youtu.be/{ID}?si=abcdef&t=10",
        f"https://www.youtube.com/shorts/{ID}",
        f"https://www.youtube.com/live/{ID}?feature=share",
        f"https://www.youtube.com/embed/{ID}",
        f"https://www.youtube-nocookie.com/embed/{ID}",
        f"  https://WWW.YOUTUBE.COM/watch?v={ID}  ",
    ],
)
def test_parse_video_id_valid(url):
    assert parse_video_id(url) == ID


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "bonjour",
        f"https://vimeo.com/{ID}",
        f"https://notyoutube.com/watch?v={ID}",
        f"https://youtube.com.evil.example/watch?v={ID}",
        f"ftp://youtube.com/watch?v={ID}",
        "https://www.youtube.com/watch?v=tooshort",
        "https://www.youtube.com/watch",
        "https://www.youtube.com/playlist?list=PLabcdefghijkl",
        "https://www.youtube.com/@SomeChannel",
        "https://www.youtube.com/channel/UCabcdefghijklmnop",
        "https://youtu.be/",
        "https://[invalid",
    ],
)
def test_parse_video_id_invalid(url):
    with pytest.raises(InvalidUrlError):
        parse_video_id(url)


def test_playlist_url_error_explains_limitation():
    with pytest.raises(InvalidUrlError) as exc:
        parse_video_id("https://www.youtube.com/playlist?list=PLabcdefghijkl")
    assert "playlist" in exc.value.user_message


def test_canonical_url_roundtrip():
    assert canonical_url(ID) == f"https://www.youtube.com/watch?v={ID}"
    assert parse_video_id(canonical_url(ID)) == ID
