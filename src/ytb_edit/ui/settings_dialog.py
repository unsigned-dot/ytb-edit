"""Boîte de dialogue des paramètres."""

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ytb_edit import paths
from ytb_edit.core.models import AudioFormat
from ytb_edit.settings import AppSettings


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Paramètres")
        self.setMinimumWidth(560)
        self._settings = settings

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.cache_edit = QLineEdit(settings.cache_dir)
        self.cache_edit.setPlaceholderText(str(paths.default_cache_dir()))
        form.addRow("Dossier temporaire :", self._with_browse(self.cache_edit))

        self.audio_combo = QComboBox()
        self.audio_combo.addItem("M4A — piste d'origine, sans réencodage", AudioFormat.M4A.value)
        self.audio_combo.addItem("MP3 — compatible partout (réencodage)", AudioFormat.MP3.value)
        self.audio_combo.setCurrentIndex(max(0, self.audio_combo.findData(settings.audio_format)))
        form.addRow("Format « Audio seul » :", self.audio_combo)

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 1000)
        self.limit_spin.setSuffix(" Go")
        self.limit_spin.setValue(settings.cache_limit_gb)
        form.addRow("Taille max. du dossier temporaire :", self.limit_spin)

        self.keep_check = QCheckBox("Conserver les fichiers sources à la fermeture")
        self.keep_check.setChecked(settings.keep_cache_on_exit)
        form.addRow("", self.keep_check)

        self.ffmpeg_edit = QLineEdit(settings.ffmpeg_dir)
        self.ffmpeg_edit.setPlaceholderText("Automatique (PATH)")
        form.addRow("Dossier de FFmpeg :", self._with_browse(self.ffmpeg_edit))
        layout.addLayout(form)

        note = QLabel("Le dossier temporaire et FFmpeg sont pris en compte au prochain démarrage.")
        note.setStyleSheet("color: gray;")
        layout.addWidget(note)

        logs_btn = QPushButton("Ouvrir le dossier des logs")
        logs_btn.clicked.connect(lambda: open_folder(paths.log_dir()))
        layout.addWidget(logs_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _with_browse(self, edit: QLineEdit) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, 1)
        button = QPushButton("Parcourir…")
        button.clicked.connect(lambda: self._browse(edit))
        row.addWidget(button)
        return container

    def _browse(self, edit: QLineEdit) -> None:
        start = edit.text() or edit.placeholderText() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choisir un dossier", start)
        if folder:
            edit.setText(folder)

    def apply_to(self, settings: AppSettings) -> None:
        settings.cache_dir = self.cache_edit.text().strip()
        settings.audio_format = self.audio_combo.currentData()
        settings.cache_limit_gb = self.limit_spin.value()
        settings.keep_cache_on_exit = self.keep_check.isChecked()
        settings.ffmpeg_dir = self.ffmpeg_edit.text().strip()


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
