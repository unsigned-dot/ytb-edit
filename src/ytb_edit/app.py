"""Point d'entrée : assemble les composants et lance l'interface."""

import logging
import sys
from pathlib import Path

from ytb_edit import APP_NAME, __version__, paths
from ytb_edit.logging_setup import setup_logging

log = logging.getLogger(__name__)


def bundled_bin_dir() -> Path:
    """Dossier ``bin`` à côté de l'application (FFmpeg embarqué, packaging futur)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "bin"
    return Path(__file__).resolve().parents[2] / "bin"


def main() -> int:
    log_file = setup_logging(paths.log_dir(), console="--debug" in sys.argv)
    log.info("Démarrage de %s %s (Python %s)", APP_NAME, __version__, sys.version.split()[0])
    log.info("Fichier de log : %s", log_file)

    # Imports locaux : les modules non graphiques restent importables sans Qt.
    from PySide6.QtWidgets import QApplication

    from ytb_edit.core.engine import Engine, EngineConfig
    from ytb_edit.services.cache import SourceCache
    from ytb_edit.services.ffmpeg import FFmpeg, find_tools
    from ytb_edit.services.media import YouTubeFFmpegMedia
    from ytb_edit.services.youtube import find_js_runtime, ytdlp_version
    from ytb_edit.settings import load_settings
    from ytb_edit.ui.bridge import EngineBridge
    from ytb_edit.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    settings = load_settings()
    tools = find_tools(settings.ffmpeg_dir or None, bundled_bin_dir())
    js_runtime = find_js_runtime()
    log.info("yt-dlp %s", ytdlp_version())
    log.info("FFmpeg : %s", tools.version if tools else "INTROUVABLE")
    log.info("Moteur JavaScript : %s", js_runtime or "INTROUVABLE")

    cache = SourceCache(settings.effective_cache_dir)
    cache.purge_incomplete()
    log.info("Dossier temporaire : %s", cache.root)

    bridge = EngineBridge()
    engine = Engine(
        YouTubeFFmpegMedia(FFmpeg(tools) if tools else None),
        cache,
        bridge.emit,
        EngineConfig(
            output_dir=Path(settings.output_dir) if settings.output_dir else None,
            audio_format=settings.audio,
            cache_limit_bytes=settings.cache_limit_gb * 1024**3,
            keep_cache_on_exit=settings.keep_cache_on_exit,
        ),
    )
    engine.start_workers()

    window = MainWindow(
        engine, bridge, settings, ffmpeg_ok=tools is not None, js_runtime_ok=js_runtime is not None
    )
    window.show()

    exit_code = app.exec()
    log.info("Arrêt (code %s)", exit_code)
    return exit_code
