import pytest

from ytb_edit.core.errors import InvalidTimecodeError
from ytb_edit.core.timecode import format_for_filename, format_time, parse_time


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # deux-points
        ("3:20", 200),
        ("03:20", 200),
        ("0:00", 0),
        ("1:02:03", 3723),
        ("75:00", 4500),
        ("3:5", 185),
        # chiffres seuls
        ("0", 0),
        ("45", 45),
        ("90", 90),
        ("320", 200),
        ("0320", 200),
        ("10203", 3723),
        # unités
        ("3m20s", 200),
        ("1h02m03s", 3723),
        ("90s", 90),
        ("1h", 3600),
        ("5m", 300),
        ("1H02M03S", 3723),
        # espaces tolérés
        ("  3:20 ", 200),
        ("3 : 20", 200),
    ],
)
def test_parse_time_valid(text, expected):
    assert parse_time(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "abc",
        "3:75",
        "1:60:00",
        "175",
        "1h75m",
        "-5",
        "-0:10",
        "3:",
        ":20",
        "1:2:3:4",
        "3.20",
        "h",
        "3:20:",
        "3m20",
        "²",
    ],
)
def test_parse_time_invalid(text):
    with pytest.raises(InvalidTimecodeError):
        parse_time(text)


def test_parse_time_error_message_is_user_friendly():
    with pytest.raises(InvalidTimecodeError) as exc:
        parse_time("abc")
    assert "abc" in exc.value.user_message


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "00:00"), (200, "03:20"), (3599, "59:59"), (3600, "1:00:00"), (3723, "1:02:03")],
)
def test_format_time(seconds, expected):
    assert format_time(seconds) == expected


@pytest.mark.parametrize(
    ("seconds", "with_hours", "expected"),
    [
        (200, False, "03m20s"),
        (0, False, "00m00s"),
        (4500, False, "75m00s"),
        (200, True, "0h03m20s"),
        (3723, True, "1h02m03s"),
    ],
)
def test_format_for_filename(seconds, with_hours, expected):
    assert format_for_filename(seconds, with_hours=with_hours) == expected


@pytest.mark.parametrize("seconds", [0, 59, 200, 3599, 3723, 36000])
def test_format_then_parse_roundtrip(seconds):
    assert parse_time(format_time(seconds)) == seconds
    assert parse_time(format_for_filename(seconds, with_hours=True)) == seconds


def test_negative_seconds_cannot_be_formatted():
    with pytest.raises(ValueError):
        format_time(-1)
