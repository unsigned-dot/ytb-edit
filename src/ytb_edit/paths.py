"""Emplacements des fichiers de l'application (paramètres, logs, cache).

Sous Windows :
- paramètres : %APPDATA%\\ytb-edit
- logs et cache : %LOCALAPPDATA%\\ytb-edit\\{logs,cache}
"""

from pathlib import Path

from platformdirs import user_config_path, user_data_path

from ytb_edit import APP_NAME


def config_dir() -> Path:
    return user_config_path(APP_NAME, appauthor=False, roaming=True)


def log_dir() -> Path:
    return user_data_path(APP_NAME, appauthor=False) / "logs"


def default_cache_dir() -> Path:
    return user_data_path(APP_NAME, appauthor=False) / "cache"
