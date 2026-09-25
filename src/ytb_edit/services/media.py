"""Implémentation réelle de ``core.engine.Media`` : yt-dlp + FFmpeg."""

import logging
from collections.abc import Callable
from pathlib import Path

from ytb_edit.core.engine import CutRequest
from ytb_edit.core.errors import FFmpegError, SourceCorruptedError, ToolMissingError
from ytb_edit.core.models import AudioFormat, OutputMode, SourceFiles, VideoInfo
from ytb_edit.services import youtube
from ytb_edit.services.ffmpeg import CutPlan, FFmpeg

log = logging.getLogger(__name__)

DURATION_TOLERANCE_S = 5.0


class YouTubeFFmpegMedia:
    def __init__(self, ffmpeg: FFmpeg | None) -> None:
        self.ffmpeg = ffmpeg

    def fetch_info(self, video_id: str) -> VideoInfo:
        return youtube.fetch_video_info(video_id)

    def download(
        self,
        info: VideoInfo,
        dest_dir: Path,
        *,
        want_video: bool,
        want_audio: bool,
        prefer_aac: bool,
        is_cancelled: Callable[[], bool],
        on_progress: Callable[[float, str], None],
    ) -> SourceFiles:
        return youtube.download_streams(
            info,
            dest_dir,
            want_video=want_video,
            want_audio=want_audio,
            prefer_aac=prefer_aac,
            is_cancelled=is_cancelled,
            on_progress=on_progress,
        )

    def validate_source(self, source: SourceFiles, info: VideoInfo) -> None:
        ffmpeg = self._require()
        checks = [(source.video_path, "video"), (source.audio_path, "audio")]
        for path, kind in checks:
            if path is None:
                continue
            try:
                probe = ffmpeg.probe(path)
            except FFmpegError as exc:
                raise SourceCorruptedError(
                    "Fichier téléchargé illisible.", details=exc.details
                ) from exc
            present = probe.has_video if kind == "video" else probe.has_audio
            if not present:
                raise SourceCorruptedError(
                    f"Piste {kind} absente du fichier téléchargé.", details=str(path)
                )
            tolerance = max(DURATION_TOLERANCE_S, info.duration_s * 0.03)
            if probe.duration is not None and info.duration_s - probe.duration > tolerance:
                raise SourceCorruptedError(
                    "Fichier téléchargé incomplet.",
                    details=f"{path}: {probe.duration:.1f} s au lieu de {info.duration_s} s",
                )
        log.info("Source validée : %s", source)

    def output_container(
        self, source: SourceFiles, mode: OutputMode, audio_format: AudioFormat
    ) -> str:
        if mode.needs_video:
            return "mp4"
        if audio_format is AudioFormat.MP3:
            return "mp3"
        assert source.audio_path is not None
        codec = self._require().probe(source.audio_path).audio_codec
        if codec == "aac":
            return "m4a"
        if codec == "opus":
            return "opus"
        return "mp3"  # autre codec : réencodage pour rester lisible partout

    def cut(
        self,
        request: CutRequest,
        *,
        is_cancelled: Callable[[], bool],
        on_progress: Callable[[float], None],
    ) -> float:
        ffmpeg = self._require()
        source, mode = request.source, request.mode
        video = source.video_path if mode.needs_video else None
        audio = source.audio_path if mode.needs_audio else None
        start = float(request.start_s)
        if video is not None:
            start = ffmpeg.find_keyframe_before(video, start)
        plan = CutPlan(
            output=request.output,
            start_s=start,
            end_s=float(request.end_s),
            video=video,
            audio=audio,
            container=request.container,
        )
        ffmpeg.cut(plan, is_cancelled=is_cancelled, on_progress=on_progress)

        result = ffmpeg.probe(request.output)
        if not result.duration or result.duration <= 0:
            raise FFmpegError("Le clip produit est vide.", details=str(request.output))
        log.info(
            "Clip créé : %s (début réel %.2f s, durée %.2f s)",
            request.output,
            start,
            result.duration,
        )
        return start

    def _require(self) -> FFmpeg:
        if self.ffmpeg is None:
            raise ToolMissingError(
                "FFmpeg est introuvable : installez-le puis relancez "
                "l'application (winget install Gyan.FFmpeg)."
            )
        return self.ffmpeg
