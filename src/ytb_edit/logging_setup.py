"""Configuration des logs techniques (diagnostic).

Les logs vont dans un fichier rotatif ; ils ne sont pas destinés à l'interface,
qui reçoit ses propres messages via les événements du moteur.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILE_NAME = "ytb-edit.log"
_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"


def setup_logging(log_dir: Path, *, level: int = logging.DEBUG, console: bool = False) -> Path:
    """Configure le logger racine et renvoie le chemin du fichier de log."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / LOG_FILE_NAME

    root = logging.getLogger()
    root.setLevel(level)
    # Rend la fonction idempotente (utile en test et en cas de relance).
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()

    file_handler = RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(console_handler)

    return log_file
