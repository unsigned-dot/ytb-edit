"""Emplacements des fichiers de l'application (paramètres, logs, cache).

Sous Windows :
- paramètres : %APPDATA%\\ytb-edit
- logs et cache : %LOCALAPPDATA%\\ytb-edit\\{logs,cache}
"""

import os
from pathlib import Path

from platformdirs import user_config_path, user_data_path

from ytb_edit import APP_NAME


def config_dir() -> Path:
    return user_config_path(APP_NAME, appauthor=False, roaming=True)


def log_dir() -> Path:
    return user_data_path(APP_NAME, appauthor=False) / "logs"


def default_cache_dir() -> Path:
    return user_data_path(APP_NAME, appauthor=False) / "cache"


def tool_search_path() -> str:
    """PATH enrichi des dossiers où winget et Deno installent leurs exécutables.

    Juste après ``winget install``, l'Explorateur Windows n'a pas toujours le PATH
    à jour : chercher aussi à ces emplacements évite un redémarrage de session.
    """
    extra = []
    if local := os.environ.get("LOCALAPPDATA"):
        extra.append(str(Path(local) / "Microsoft" / "WinGet" / "Links"))
    extra.append(str(Path.home() / ".deno" / "bin"))
    return os.pathsep.join([os.environ.get("PATH", ""), *extra])
