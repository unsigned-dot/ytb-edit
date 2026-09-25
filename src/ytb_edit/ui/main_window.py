"""Fenêtre principale : assemble les widgets et relaie commandes/événements."""

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ytb_edit import APP_NAME, __version__
from ytb_edit.core.engine import Engine
from ytb_edit.core.errors import AppError
from ytb_edit.core.events import (
    Event,
    Notice,
    Progress,
    QueueIdle,
    QueueStateChanged,
    TaskChanged,
    TaskRemoved,
)
from ytb_edit.core.models import OutputMode, SegmentStatus, TaskStatus, VideoTask
from ytb_edit.settings import AppSettings, save_settings
from ytb_edit.ui.bridge import EngineBridge
from ytb_edit.ui.labels import MODE_LABELS
from ytb_edit.ui.queue_view import QueueView
from ytb_edit.ui.settings_dialog import SettingsDialog, open_folder
from ytb_edit.ui.task_panel import TaskPanel

log = logging.getLogger(__name__)

_BANNER_STYLE = (
    "QLabel { background: #fff3cd; color: #664d03; border: 1px solid #ffe69c;"
    " padding: 6px; border-radius: 4px; }"
)


class MainWindow(QMainWindow):
    def __init__(
        self,
        engine: Engine,
        bridge: EngineBridge,
        settings: AppSettings,
        *,
        ffmpeg_ok: bool,
        js_runtime_ok: bool,
    ) -> None:
        super().__init__()
        self.engine = engine
        self.settings = settings
        self.ffmpeg_ok = ffmpeg_ok
        self._tasks: dict[str, VideoTask] = {}
        self._pending_select: str | None = None

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1200, 780)

        central = QWidget()
        root = QVBoxLayout(central)

        # --- bandeau d'avertissement
        warnings = []
        if not ffmpeg_ok:
            warnings.append(
                "FFmpeg est introuvable : la découpe est impossible. Installez-le "
                "(<b>winget install Gyan.FFmpeg</b>) puis relancez l'application, "
                "ou indiquez son dossier dans les Paramètres."
            )
        if not js_runtime_ok:
            warnings.append(
                "Aucun moteur JavaScript (Deno) trouvé : certaines vidéos YouTube "
                "peuvent échouer. Installez-le : <b>winget install DenoLand.Deno</b>."
            )
        if warnings:
            banner = QLabel("<br>".join(warnings))
            banner.setWordWrap(True)
            banner.setStyleSheet(_BANNER_STYLE)
            root.addWidget(banner)

        # --- dossier de sortie
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Dossier de sortie :"))
        self.output_edit = QLineEdit(settings.output_dir)
        self.output_edit.setReadOnly(True)
        self.output_edit.setPlaceholderText("Choisissez où enregistrer les clips…")
        out_row.addWidget(self.output_edit, 1)
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self.choose_output_dir)
        out_row.addWidget(browse)
        open_out = QPushButton("Ouvrir")
        open_out.clicked.connect(self._open_output_dir)
        out_row.addWidget(open_out)
        settings_btn = QPushButton("⚙ Paramètres")
        settings_btn.clicked.connect(self._open_settings)
        out_row.addWidget(settings_btn)
        root.addLayout(out_row)

        # --- ajout d'URL
        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("URL YouTube :"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Collez une URL puis Entrée (ex. https://youtu.be/…)")
        self.url_edit.returnPressed.connect(self._add_url)
        url_row.addWidget(self.url_edit, 1)
        self.mode_combo = QComboBox()
        for mode in OutputMode:
            self.mode_combo.addItem(MODE_LABELS[mode], mode.value)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(settings.mode.value)))
        url_row.addWidget(self.mode_combo)
        add_btn = QPushButton("Ajouter")
        add_btn.clicked.connect(self._add_url)
        url_row.addWidget(add_btn)
        root.addLayout(url_row)
        self.url_error = QLabel("")
        self.url_error.setStyleSheet("color: #c9302c;")
        self.url_error.hide()
        root.addWidget(self.url_error)

        # --- file + panneau
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.queue = QueueView()
        self.queue.task_selected.connect(self._on_task_selected)
        splitter.addWidget(self.queue)
        self.panel = TaskPanel()
        splitter.addWidget(self.panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([520, 680])
        root.addWidget(splitter, 1)
        self._connect_panel()

        # --- barre de progression globale
        bottom = QHBoxLayout()
        self.start_btn = QPushButton()
        self.start_btn.setMinimumWidth(170)
        self.start_btn.clicked.connect(self._toggle_queue)
        bottom.addWidget(self.start_btn)
        self.stats_label = QLabel("")
        bottom.addWidget(self.stats_label)
        self.global_bar = QProgressBar()
        self.global_bar.setRange(0, 1000)
        self.global_bar.setTextVisible(False)
        bottom.addWidget(self.global_bar, 1)
        root.addLayout(bottom)
        self.activity_label = QLabel("")
        root.addWidget(self.activity_label)

        self.activity_log = QListWidget()
        self.activity_log.setMaximumHeight(120)
        root.addWidget(self.activity_log)

        self.setCentralWidget(central)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.url_edit.setFocus)

        bridge.event_received.connect(self._on_event)
        self._update_start_button()
        self._update_stats()

    # ------------------------------------------------------------------ actions

    def choose_output_dir(self) -> bool:
        start = self.settings.output_dir or str(Path.home() / "Videos")
        folder = QFileDialog.getExistingDirectory(self, "Dossier de sortie des clips", start)
        if not folder:
            return False
        self.settings.output_dir = folder
        self.output_edit.setText(folder)
        self.engine.configure(output_dir=Path(folder))
        save_settings(self.settings)
        self._update_start_button()
        return True

    def _open_output_dir(self) -> None:
        if self.settings.output_dir:
            open_folder(Path(self.settings.output_dir))

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            dialog.apply_to(self.settings)
            save_settings(self.settings)
            self.engine.configure(
                audio_format=self.settings.audio,
                cache_limit_bytes=self.settings.cache_limit_gb * 1024**3,
                keep_cache_on_exit=self.settings.keep_cache_on_exit,
            )

    def _add_url(self) -> None:
        text = self.url_edit.text().strip()
        if not text:
            return
        mode = OutputMode(self.mode_combo.currentData())
        try:
            task_id, is_new = self.engine.add_video(text, mode)
        except AppError as exc:
            self.url_error.setText(exc.user_message)
            self.url_error.show()
            return
        self.url_error.hide()
        self.url_edit.clear()
        if mode is not self.settings.mode:
            self.settings.default_mode = mode.value
            save_settings(self.settings)
        if is_new:
            self._pending_select = task_id
        else:
            self._log("Cette vidéo est déjà dans la file.")
        self.queue.select_task(task_id)

    def _toggle_queue(self) -> None:
        if self.engine.running:
            self.engine.pause()
            return
        if not self.ffmpeg_ok:
            QMessageBox.warning(
                self, APP_NAME, "FFmpeg est introuvable : installez-le puis relancez l'application."
            )
            return
        if not self.settings.output_dir and not self.choose_output_dir():
            return
        self.engine.configure(output_dir=Path(self.settings.output_dir))
        self.engine.start()

    def _connect_panel(self) -> None:
        panel, engine = self.panel, self.engine

        def call(func, *args):  # exécute une commande et affiche l'erreur éventuelle
            try:
                func(*args)
                return True
            except AppError as exc:
                QMessageBox.warning(self, APP_NAME, exc.user_message)
                return False

        def add_segment(task_id: str, start: int, end: int) -> None:
            if call(engine.add_segment, task_id, start, end):
                panel.after_segment_added()

        panel.add_segment_requested.connect(add_segment)
        panel.update_segment_requested.connect(lambda *a: call(engine.update_segment, *a))
        panel.remove_segment_requested.connect(lambda *a: call(engine.remove_segment, *a))
        panel.cancel_segment_requested.connect(lambda *a: call(engine.cancel_segment, *a))
        panel.mode_change_requested.connect(lambda *a: call(engine.set_mode, *a))
        panel.cancel_task_requested.connect(lambda t: call(engine.cancel_task, t))
        panel.retry_task_requested.connect(lambda t: call(engine.retry_task, t))
        panel.remove_task_requested.connect(self._remove_task)

    def _remove_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task and task.status in (TaskStatus.DOWNLOADING, TaskStatus.PROCESSING):
            answer = QMessageBox.question(
                self,
                APP_NAME,
                "Cette vidéo est en cours de traitement. L'annuler et la retirer de la file ?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.engine.remove_task(task_id)

    # ------------------------------------------------------------------ événements

    def _on_event(self, event: Event) -> None:
        if isinstance(event, TaskChanged):
            task = event.task
            self._tasks[task.id] = task
            self.queue.update_task(task)
            if self._pending_select == task.id:
                self._pending_select = None
                self.queue.select_task(task.id)
            if self.panel.current_task_id() == task.id:
                self.panel.set_task(task)
            self._update_stats()
        elif isinstance(event, TaskRemoved):
            self._tasks.pop(event.task_id, None)
            self.queue.remove_task(event.task_id)
            if self.panel.current_task_id() == event.task_id:
                self.panel.set_task(None)
            self._update_stats()
        elif isinstance(event, Progress):
            task = self._tasks.get(event.task_id)
            percent = f"{event.fraction:.0%}"
            if task and task.status is TaskStatus.DOWNLOADING:
                self.queue.set_progress(event.task_id, percent)
            title = task.title if task else ""
            self.activity_label.setText(f"{title} — {event.text} — {percent}")
        elif isinstance(event, Notice):
            self._log(event.text, error=event.error)
        elif isinstance(event, QueueStateChanged):
            self._update_start_button()
            if not event.running:
                self.activity_label.setText(
                    "File en pause : les opérations en cours se "
                    "terminent, aucune nouvelle ne démarre."
                )
        elif isinstance(event, QueueIdle):
            self.activity_label.setText("Traitement terminé.")
            self._show_summary(event)

    def _on_task_selected(self, task_id: str | None) -> None:
        self.panel.set_task(self._tasks.get(task_id) if task_id else None)

    def _show_summary(self, event: QueueIdle) -> None:
        summary = event.summary
        if summary.videos == 0:
            return
        text = (
            f"{summary.videos} vidéo(s) traitée(s)\n{summary.clips} clip(s) créé(s)\n"
            f"{summary.errors} erreur(s)\n\n" + "\n".join(summary.lines)
        )
        box = QMessageBox(
            QMessageBox.Icon.Information,
            "Traitement terminé",
            text,
            QMessageBox.StandardButton.Ok,
            self,
        )
        box.setModal(False)
        box.show()

    def _log(self, text: str, *, error: bool = False) -> None:
        item = QListWidgetItem(text)
        if error:
            item.setForeground(Qt.GlobalColor.red)
        self.activity_log.addItem(item)
        self.activity_log.scrollToBottom()

    def _update_start_button(self) -> None:
        running = self.engine.running
        self.start_btn.setText("⏸ Mettre en pause" if running else "▶ Démarrer la file")

    def _update_stats(self) -> None:
        tasks = [t for t in self._tasks.values() if t.segments]
        segments = [s for t in tasks for s in t.segments if s.status is not SegmentStatus.CANCELLED]
        done = sum(1 for s in segments if s.status is SegmentStatus.DONE)
        failed_segments = sum(1 for s in segments if s.status is SegmentStatus.FAILED)
        failed_tasks = sum(1 for t in self._tasks.values() if t.status is TaskStatus.FAILED)
        finished = sum(1 for t in tasks if t.status is TaskStatus.COMPLETED)
        errors = failed_segments + failed_tasks
        self.stats_label.setText(
            f"Vidéos {finished}/{len(tasks)} · Segments {done}/{len(segments)} · {errors} erreur(s)"
        )
        self.global_bar.setValue(int(1000 * done / len(segments)) if segments else 0)

    # ------------------------------------------------------------------ fermeture

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.engine.is_busy():
            answer = QMessageBox.question(
                self, APP_NAME, "Des traitements sont en cours. Quitter et les annuler ?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.activity_label.setText("Arrêt en cours…")
        self.engine.shutdown()
        save_settings(self.settings)
        event.accept()
