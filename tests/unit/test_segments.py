import pytest

from ytb_edit.core.errors import InvalidSegmentError
from ytb_edit.core.segments import shift_time, suggest_next_segment, validate_segment


@pytest.mark.parametrize(
    ("start", "end", "duration"),
    [(0, 1, 10), (200, 230, 600), (0, 600, 600), (100, 200, None)],
)
def test_valid_segments(start, end, duration):
    validate_segment(start, end, duration)


@pytest.mark.parametrize(
    ("start", "end", "duration", "fragment"),
    [
        (-1, 10, 600, "négatif"),
        (10, -1, 600, "négatif"),
        (30, 30, 600, "après le début"),
        (50, 30, 600, "après le début"),
        (590, 601, 600, "dépasse"),
        (700, 800, 600, "dépasse"),
    ],
)
def test_invalid_segments(start, end, duration, fragment):
    with pytest.raises(InvalidSegmentError) as exc:
        validate_segment(start, end, duration)
    assert fragment in exc.value.user_message


def test_out_of_range_message_shows_readable_times():
    with pytest.raises(InvalidSegmentError) as exc:
        validate_segment(3000, 4000, 3723)
    assert "1:06:40" in exc.value.user_message
    assert "1:02:03" in exc.value.user_message


@pytest.mark.parametrize(
    ("value", "delta", "duration", "expected"),
    [
        (200, 10, 600, 210),
        (200, -10, 600, 190),
        (5, -10, 600, 0),
        (595, 10, 600, 600),
        (595, 10, None, 605),
    ],
)
def test_shift_time_stays_in_bounds(value, delta, duration, expected):
    assert shift_time(value, delta, duration) == expected


@pytest.mark.parametrize(
    ("previous_end", "duration", "expected"),
    [
        (None, 600, (0, 30)),
        (230, 600, (230, 260)),
        (590, 600, (590, 600)),  # tronqué à la fin de la vidéo
        (600, 600, (570, 600)),  # plus de place : recalé sur la fin
        (None, 20, (0, 20)),  # vidéo plus courte que la durée par défaut
    ],
)
def test_suggest_next_segment(previous_end, duration, expected):
    start, end = suggest_next_segment(previous_end, duration)
    assert (start, end) == expected
    validate_segment(start, end, duration)
