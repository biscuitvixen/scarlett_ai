import pytest

from scarlett.cogs.music import _format_duration, _progress_bar


@pytest.mark.parametrize(
    "ms, expected",
    [
        (0, "0:00"),
        (-5000, "0:00"),  # position can briefly read negative, clamp it
        (5000, "0:05"),
        (65000, "1:05"),
        (600000, "10:00"),
        (3661000, "1:01:01"),  # rolls over into hours
    ],
)
def test_format_duration(ms, expected):
    assert _format_duration(ms) == expected


def test_progress_bar_width_is_constant():
    # whatever the position, the bar is always exactly `width` characters
    for pos in (0, 25, 50, 99, 100):
        assert len(_progress_bar(pos, 100, width=10)) == 10


def test_progress_bar_start_and_end():
    assert _progress_bar(0, 100, width=10) == "●" + "─" * 9
    assert _progress_bar(100, 100, width=10) == "━" * 10
    assert _progress_bar(50, 100, width=10) == "━" * 5 + "●" + "─" * 4


def test_progress_bar_zero_length_does_not_crash():
    # a livestream or a not-yet-loaded track reports length 0
    assert _progress_bar(0, 0, width=10) == "●" + "─" * 9
