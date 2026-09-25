"""Construction des commandes FFmpeg (sans exécuter FFmpeg)."""

from pathlib import Path

import pytest

from ytb_edit.services.ffmpeg import CutPlan, build_cut_command, parse_keyframes

V, A, OUT = Path("v.webm"), Path("a.m4a"), Path("out.part.mp4")


def _value(args: list[str], flag: str, occurrence: int = 0) -> str:
    indexes = [i for i, a in enumerate(args) if a == flag]
    return args[indexes[occurrence] + 1]


def test_audio_video_command_uses_combined_seek():
    args = build_cut_command("ffmpeg", CutPlan(OUT, 200.0, 230.0, video=V, audio=A))
    # recherche rapide en entrée (10 s avant), identique pour les deux entrées
    assert args.count("-ss") == 3
    assert _value(args, "-ss", 0) == "190.000" and _value(args, "-ss", 1) == "190.000"
    # coupe précise en sortie, 0,1 s avant l'image clé
    assert _value(args, "-ss", 2) == "9.900"
    assert _value(args, "-t") == "30.100"
    assert args[args.index("-map") : args.index("-map") + 4] == ["-map", "0:v:0", "-map", "1:a:0"]
    assert "copy" in args and "mp4" in args and "+faststart" in args
    assert args[-1] == str(OUT)
    assert "-n" not in args  # le .part nous appartient ; le nom final est vérifié à part


def test_start_near_beginning_has_no_input_seek():
    args = build_cut_command("ffmpeg", CutPlan(OUT, 4.0, 9.0, video=V, audio=A))
    assert args.count("-ss") == 1
    assert _value(args, "-ss") == "3.900"


def test_keyframe_at_zero_has_no_seek_at_all():
    args = build_cut_command("ffmpeg", CutPlan(OUT, 0.0, 9.0, video=V, audio=A))
    assert "-ss" not in args
    assert _value(args, "-t") == "9.000"


def test_video_only_command():
    args = build_cut_command("ffmpeg", CutPlan(OUT, 60.0, 70.0, video=V))
    assert "-an" in args and "1:a:0" not in args


@pytest.mark.parametrize(
    ("container", "expected"),
    [("m4a", ["-f", "ipod"]), ("opus", ["-f", "opus"]), ("mp3", ["libmp3lame"])],
)
def test_audio_only_commands(container, expected):
    args = build_cut_command("ffmpeg", CutPlan(OUT, 200.0, 230.0, audio=A, container=container))
    assert "-vn" in args and args[args.index("-map") : args.index("-map") + 2] == ["-map", "0:a:0"]
    assert all(e in args for e in expected)
    # pas de marge de 0,1 s sans vidéo : coupe exacte
    assert _value(args, "-ss", 1) == "10.000"
    assert _value(args, "-t") == "30.000"


def test_command_requires_an_input():
    with pytest.raises(ValueError):
        build_cut_command("ffmpeg", CutPlan(OUT, 0.0, 1.0))


def test_parse_keyframes():
    output = "10.000000,K__\n10.033333,___\nN/A,K__\n12.000000,K_\n13.000000,K__\n"
    assert parse_keyframes(output, 12.5) == [10.0, 12.0]
    assert parse_keyframes("", 5) == []
