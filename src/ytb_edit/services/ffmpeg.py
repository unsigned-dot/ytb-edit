"""FFmpeg / ffprobe : détection, analyse des fichiers, découpe sans réencodage.

Stratégie de découpe (validée sur VP9/webm et H.264/mp4, audio Opus et AAC) :

1. ``ffprobe`` lit les paquets vidéo (sans décodage) et trouve ``K``, la dernière
   image clé ≤ début demandé : en copie de flux, une vidéo ne peut commencer que là.
2. Recherche combinée :
   - en entrée, ``-ss (K - 10 s)`` sur chaque entrée : saut rapide dans le fichier ;
   - en sortie, ``-ss`` jusqu'à ``K - 0,1 s`` : coupe exacte au paquet près,
     identique pour toutes les entrées, donc audio et vidéo restent synchronisés.
   Les 0,1 s de marge évitent que FFmpeg saute l'image clé ``K`` (son temps de
   décodage précède son temps d'affichage quand la vidéo contient des images B).
   FFmpeg ignore les paquets vidéo avant ``K`` : le clip commence sur l'image clé,
   avec au plus 0,1 s d'audio en tête.
"""

import contextlib
import json
import logging
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ytb_edit import paths
from ytb_edit.core.errors import FFmpegError, ToolMissingError
from ytb_edit.services import process

log = logging.getLogger(__name__)

SEEK_LEAD_S = 10.0
KEYFRAME_MARGIN_S = 0.1
_EXE = ".exe" if sys.platform == "win32" else ""


@dataclass(frozen=True)
class FFmpegTools:
    ffmpeg: str
    ffprobe: str
    version: str


def find_tools(
    custom_dir: str | None = None, bundled_dir: Path | None = None
) -> FFmpegTools | None:
    """Cherche ffmpeg et ffprobe : dossier des paramètres → dossier ``bin`` → PATH."""
    candidates: list[tuple[str | None, str | None]] = []
    for directory in (custom_dir, bundled_dir):
        if directory:
            d = Path(directory)
            candidates.append((str(d / f"ffmpeg{_EXE}"), str(d / f"ffprobe{_EXE}")))
    search = paths.tool_search_path()
    candidates.append((shutil.which("ffmpeg", path=search), shutil.which("ffprobe", path=search)))

    for ffmpeg, ffprobe in candidates:
        if ffmpeg and ffprobe and Path(ffmpeg).is_file() and Path(ffprobe).is_file():
            try:
                result = process.run([ffmpeg, "-hide_banner", "-version"], timeout=15)
            except (OSError, TimeoutError) as exc:
                log.warning("FFmpeg inutilisable (%s) : %s", ffmpeg, exc)
                continue
            if result.returncode == 0:
                version = result.stdout.splitlines()[0] if result.stdout else "?"
                return FFmpegTools(ffmpeg, ffprobe, version)
    return None


@dataclass(frozen=True)
class ProbeResult:
    duration: float | None
    has_video: bool
    has_audio: bool
    video_codec: str | None
    audio_codec: str | None


@dataclass(frozen=True)
class CutPlan:
    """Paramètres complets d'une découpe."""

    output: Path
    start_s: float  # début effectif (image clé pour les modes avec vidéo)
    end_s: float
    video: Path | None = None
    audio: Path | None = None
    # "mp4" (avec vidéo), "m4a" (AAC copié), "opus" (Opus copié), "mp3" (réencodé)
    container: str = "mp4"


class FFmpeg:
    def __init__(self, tools: FFmpegTools) -> None:
        self.tools = tools

    # --- analyse -------------------------------------------------------------

    def probe(self, path: Path) -> ProbeResult:
        args = [
            self.tools.ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name",
            "-of",
            "json",
            str(path),
        ]
        result = self._run(args, timeout=120)
        if result.returncode != 0:
            raise FFmpegError(
                "Fichier illisible par FFmpeg.", details=f"{path}: {result.stderr_tail}"
            )
        try:
            data = json.loads(result.stdout or "{}")
        except ValueError as exc:
            raise FFmpegError("Réponse inattendue de ffprobe.", details=str(exc)) from exc
        streams = data.get("streams") or []
        video = next(
            (
                s
                for s in streams
                if s.get("codec_type") == "video" and s.get("codec_name") not in ("mjpeg", "png")
            ),
            None,
        )
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        try:
            duration = float(data.get("format", {}).get("duration"))
        except (TypeError, ValueError):
            duration = None
        return ProbeResult(
            duration,
            video is not None,
            audio is not None,
            video and video.get("codec_name"),
            audio and audio.get("codec_name"),
        )

    def find_keyframe_before(self, video: Path, t: float) -> float:
        """Temps de la dernière image clé ≤ ``t`` (0 si aucune trouvée)."""
        for window in (30.0, 300.0, None):
            low = 0.0 if window is None else max(0.0, t - window)
            args = [
                self.tools.ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "packet=pts_time,flags",
                "-of",
                "csv=p=0",
                "-read_intervals",
                f"{low:.3f}%{t + 0.5:.3f}",
                str(video),
            ]
            result = self._run(args, timeout=300)
            if result.returncode != 0:
                raise FFmpegError("Analyse des images clés impossible.", details=result.stderr_tail)
            keyframes = parse_keyframes(result.stdout, t)
            if keyframes:
                return max(keyframes)
            if low == 0.0:
                break
        return 0.0

    # --- découpe -------------------------------------------------------------

    def cut(
        self,
        plan: CutPlan,
        *,
        is_cancelled: Callable[[], bool],
        on_progress: Callable[[float], None] | None = None,
    ) -> None:
        args = build_cut_command(self.tools.ffmpeg, plan)
        log.info("FFmpeg : %s", " ".join(args))
        total = max(plan.end_s - plan.start_s, 0.001)

        def on_line(line: str) -> None:
            if on_progress and line.startswith("out_time_us="):
                with contextlib.suppress(ValueError):  # "N/A" au tout début
                    on_progress(min(int(line.split("=", 1)[1]) / 1e6 / total, 1.0))

        result = process.run(args, is_cancelled=is_cancelled, on_stdout_line=on_line)
        if result.returncode != 0:
            raise FFmpegError(_ffmpeg_message(result.stderr_tail), details=result.stderr_tail)

    def _run(self, args: list[str], *, timeout: float) -> process.ProcessResult:
        try:
            return process.run(args, timeout=timeout)
        except FileNotFoundError as exc:
            raise ToolMissingError("FFmpeg introuvable.", details=str(exc)) from exc
        except TimeoutError as exc:
            raise FFmpegError("FFmpeg ne répond pas.", details=str(exc)) from exc


def parse_keyframes(csv_output: str, t: float) -> list[float]:
    """Extrait les temps des images clés ≤ ``t`` d'une sortie ``pts_time,flags``."""
    keyframes = []
    for line in csv_output.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 2 or "K" not in parts[1]:
            continue
        try:
            pts = float(parts[0])
        except ValueError:  # "N/A"
            continue
        if pts <= t + 0.001:
            keyframes.append(pts)
    return keyframes


def build_cut_command(ffmpeg: str, plan: CutPlan) -> list[str]:
    """Commande FFmpeg d'une découpe (fonction pure, testée unitairement)."""
    if plan.video is None and plan.audio is None:
        raise ValueError("Aucune entrée")
    has_video = plan.video is not None
    inputs = [p for p in (plan.video, plan.audio) if p is not None]

    seek = max(0.0, plan.start_s - SEEK_LEAD_S)
    margin = KEYFRAME_MARGIN_S if has_video else 0.0
    offset = max(0.0, plan.start_s - seek - margin)
    duration = plan.end_s - (seek + offset)

    args = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-nostats",
        "-progress",
        "pipe:1",
        "-y",
    ]
    for path in inputs:
        if seek > 0:
            args += ["-ss", _fmt(seek)]
        args += ["-i", str(path)]
    if offset > 0:
        args += ["-ss", _fmt(offset)]
    args += ["-t", _fmt(duration)]

    if has_video:
        args += ["-map", "0:v:0"]
    if plan.audio is not None:
        args += ["-map", f"{1 if has_video else 0}:a:0"]

    if plan.container == "mp3":
        args += ["-c:a", "libmp3lame", "-q:a", "0", "-f", "mp3"]
    else:
        args += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        args += {
            "mp4": ["-f", "mp4", "-movflags", "+faststart"],
            "m4a": ["-f", "ipod", "-movflags", "+faststart"],
            "opus": ["-f", "opus"],
        }[plan.container]
    if not has_video:
        args += ["-vn"]
    elif plan.audio is None:
        args += ["-an"]
    args += ["-map_metadata", "-1", "-map_chapters", "-1", str(plan.output)]
    return args


def _fmt(seconds: float) -> str:
    return f"{seconds:.3f}"


def _ffmpeg_message(stderr: str) -> str:
    lowered = stderr.lower()
    if "no space left" in lowered or "not enough space" in lowered:
        return "Espace disque insuffisant pendant la découpe."
    if "could not find tag for codec" in lowered or "not supported" in lowered:
        return "Format incompatible avec le conteneur de sortie (voir les logs)."
    if "invalid data found" in lowered or "moov atom not found" in lowered:
        return "Fichier source corrompu."
    return "Échec de FFmpeg pendant la découpe (voir les logs)."
