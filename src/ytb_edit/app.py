"""Point d'entrée : assemble les composants et lance l'interface.

À ce stade (étape 2), seule une fenêtre vide est affichée pour vérifier
l'installation. Le moteur et la vraie interface viendront aux étapes suivantes.
"""

import logging
import sys

from ytb_edit import APP_NAME, __version__, paths
from ytb_edit.logging_setup import setup_logging

log = logging.getLogger(__name__)


def main() -> int:
    log_file = setup_logging(paths.log_dir(), console="--debug" in sys.argv)
    log.info("Démarrage de %s %s (Python %s)", APP_NAME, __version__, sys.version.split()[0])
    log.info("Fichier de log : %s", log_file)

    # Import local : les modules non graphiques restent importables sans Qt.
    from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    window = QMainWindow()
    window.setWindowTitle(f"{APP_NAME} {__version__}")
    window.setCentralWidget(QLabel("Installation OK — l'interface arrive à l'étape 9."))
    window.resize(800, 500)
    window.show()

    exit_code = app.exec()
    log.info("Arrêt (code %s)", exit_code)
    return exit_code
