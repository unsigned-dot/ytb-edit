"""Panneau de droite : vidéo sélectionnée, mode, segments et saisie des temps."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)
from superqt import QRangeSlider

from ytb_edit.core.errors import InvalidSegmentError
from ytb_edit.core.models import OutputMode, SegmentStatus, TaskStatus, VideoTask
from ytb_edit.core.segments import suggest_next_segment, validate_segment
from ytb_edit.core.timecode import format_time
from ytb_edit.ui.labels import MODE_LABELS, segment_text, task_status_text
from ytb_edit.ui.time_input import TimeInput


class TaskPanel(QWidget):
    """Émet des demandes ; la fenêtre principale les transmet au moteur."""

    add_segment_requested = Signal(str, int, int)
    update_segment_requested = Signal(str, str, int, int)
    remove_segment_requested = Signal(str, str)
    cancel_segment_requested = Signal(str, str)
    mode_change_requested = Signal(str, object)
    cancel_task_requested = Signal(str)
    retry_task_requested = Signal(str)
    remove_task_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._task: VideoTask | None = None
        self._editing_segment: str | None = None

        layout = QVBoxLayout(self)

        self.title = QLabel("Aucune vidéo sélectionnée")
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.details = QLabel("")
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.details)
        layout.addWidget(self.status)

        # --- mode
        mode_box = QGroupBox("Mode de sortie")
        mode_layout = QHBoxLayout(mode_box)
        self.mode_group = QButtonGroup(self)
        self.mode_buttons: dict[OutputMode, QRadioButton] = {}
        for mode in OutputMode:
            button = QRadioButton(MODE_LABELS[mode])
            self.mode_buttons[mode] = button
            self.mode_group.addButton(button)
            mode_layout.addWidget(button)
            button.toggled.connect(lambda checked, m=mode: checked and self._on_mode(m))
        layout.addWidget(mode_box)

        # --- segments
        segments_box = QGroupBox("Segments")
        seg_layout = QVBoxLayout(segments_box)
        self.segment_list = QListWidget()
        self.segment_list.setMinimumHeight(110)
        self.segment_list.currentItemChanged.connect(self._on_segment_selected)
        seg_layout.addWidget(self.segment_list)
        seg_buttons = QHBoxLayout()
        self.remove_segment_btn = QPushButton("Supprimer")
        self.remove_segment_btn.clicked.connect(self._on_remove_segment)
        self.cancel_segment_btn = QPushButton("Annuler le segment")
        self.cancel_segment_btn.clicked.connect(self._on_cancel_segment)
        seg_buttons.addWidget(self.remove_segment_btn)
        seg_buttons.addWidget(self.cancel_segment_btn)
        seg_buttons.addStretch(1)
        seg_layout.addLayout(seg_buttons)
        layout.addWidget(segments_box, 1)

        # --- saisie
        form_box = QGroupBox("Nouveau segment")
        self.form_box = form_box
        form = QVBoxLayout(form_box)
        self.start_input = TimeInput("Début")
        self.end_input = TimeInput("Fin")
        form.addWidget(self.start_input)
        form.addWidget(self.end_input)
        self.slider = QRangeSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1)
        form.addWidget(self.slider)
        self.form_info = QLabel("")
        form.addWidget(self.form_info)
        form_buttons = QHBoxLayout()
        self.add_btn = QPushButton("Ajouter le segment")
        self.add_btn.setDefault(True)
        self.add_btn.clicked.connect(self._on_add)
        self.save_btn = QPushButton("Enregistrer la modification")
        self.save_btn.clicked.connect(self._on_save)
        self.new_btn = QPushButton("Nouveau")
        self.new_btn.clicked.connect(self._reset_form)
        form_buttons.addWidget(self.add_btn)
        form_buttons.addWidget(self.save_btn)
        form_buttons.addWidget(self.new_btn)
        form_buttons.addStretch(1)
        form.addLayout(form_buttons)
        layout.addWidget(form_box)

        self.start_input.valueChanged.connect(self._on_inputs_changed)
        self.end_input.valueChanged.connect(self._on_inputs_changed)
        self.start_input.edit.returnPressed.connect(self._on_enter)
        self.end_input.edit.returnPressed.connect(self._on_enter)
        self.slider.valueChanged.connect(self._on_slider)

        # --- actions sur la vidéo
        task_buttons = QHBoxLayout()
        self.cancel_task_btn = QPushButton("Annuler la vidéo")
        self.retry_btn = QPushButton("Réessayer")
        self.remove_task_btn = QPushButton("Terminer / retirer de la file")
        self.remove_task_btn.setToolTip(
            "Retire la vidéo de la file et supprime son fichier "
            "source temporaire. Les clips créés sont conservés."
        )
        self.cancel_task_btn.clicked.connect(lambda: self._emit_task(self.cancel_task_requested))
        self.retry_btn.clicked.connect(lambda: self._emit_task(self.retry_task_requested))
        self.remove_task_btn.clicked.connect(lambda: self._emit_task(self.remove_task_requested))
        task_buttons.addWidget(self.cancel_task_btn)
        task_buttons.addWidget(self.retry_btn)
        task_buttons.addStretch(1)
        task_buttons.addWidget(self.remove_task_btn)
        layout.addLayout(task_buttons)

        self.set_task(None)

    # ------------------------------------------------------------------ mise à jour

    def current_task_id(self) -> str | None:
        return self._task.id if self._task else None

    def set_task(self, task: VideoTask | None) -> None:
        """Affiche une tâche (ou rien). Ne réinitialise la saisie qu'en changeant de vidéo
        ou quand la durée devient connue."""
        previous = self._task
        self._task = task
        same = previous is not None and task is not None and previous.id == task.id
        info_arrived = same and previous.info is None and task.info is not None

        enabled = task is not None
        for widget in (self.cancel_task_btn, self.retry_btn, self.remove_task_btn):
            widget.setEnabled(enabled)
        if task is None:
            self.title.setText("Aucune vidéo sélectionnée")
            self.details.setText("Collez une URL YouTube en haut de la fenêtre.")
            self.status.setText("")
            self.segment_list.clear()
            self._set_form_enabled(False)
            for button in self.mode_buttons.values():
                button.setEnabled(False)
            return

        self.title.setText(task.title)
        info = task.info
        if info:
            megabytes = (info.estimated_size or 0) / 1_048_576
            size = f" — ~{megabytes:.0f} Mo" if megabytes >= 1 else ""
            uploader = f" — {info.uploader}" if info.uploader else ""
            self.details.setText(f"Durée : {format_time(info.duration_s)}{uploader}{size}")
        else:
            self.details.setText(task.url)
        status = task_status_text(task)
        if task.error:
            status += f" : {task.error}"
            self.status.setStyleSheet("color: #c9302c;")
        else:
            self.status.setStyleSheet("")
        self.status.setText(status)

        # mode
        for mode, button in self.mode_buttons.items():
            available = info is None or (
                (not mode.needs_audio or info.has_audio)
                and (not mode.needs_video or info.has_video)
            )
            button.setEnabled(available and task.status is not TaskStatus.CANCELLED)
            button.blockSignals(True)
            button.setChecked(mode is task.mode)
            button.blockSignals(False)

        self.retry_btn.setEnabled(
            task.status in (TaskStatus.FAILED, TaskStatus.CANCELLED)
            or any(
                s.status in (SegmentStatus.FAILED, SegmentStatus.CANCELLED) for s in task.segments
            )
        )
        self.cancel_task_btn.setEnabled(
            task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
        )

        self._refresh_segments(task)
        self._set_form_enabled(info is not None and task.status is not TaskStatus.CANCELLED)
        if info is not None:
            self.slider.setRange(0, info.duration_s)
            self.start_input.setMaximum(info.duration_s)
            self.end_input.setMaximum(info.duration_s)
            if not same or info_arrived:
                self._reset_form()
            else:
                self._validate()

    def _refresh_segments(self, task: VideoTask) -> None:
        current = self._selected_segment_id()
        self.segment_list.blockSignals(True)
        self.segment_list.clear()
        for segment in task.segments:
            text = segment_text(segment)
            if segment.status is SegmentStatus.DONE and segment.output_path:
                text += f"   → {segment.output_path.name}"
                if segment.actual_start_s is not None and segment.actual_start_s < segment.start_s:
                    text += f"  (début réel {format_time(segment.actual_start_s)})"
            elif segment.error:
                text += f"   — {segment.error}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, segment.id)
            if segment.status is SegmentStatus.FAILED:
                item.setForeground(Qt.GlobalColor.red)
            self.segment_list.addItem(item)
            if segment.id == current:
                self.segment_list.setCurrentItem(item)
        self.segment_list.blockSignals(False)
        if self._editing_segment and not any(
            s.id == self._editing_segment and s.status is SegmentStatus.PENDING
            for s in task.segments
        ):
            self._editing_segment = None
        self._update_segment_buttons()

    # ------------------------------------------------------------------ saisie

    def _reset_form(self) -> None:
        self._editing_segment = None
        self.segment_list.clearSelection()
        task = self._task
        if task is None or task.info is None:
            return
        last_end = task.segments[-1].end_s if task.segments else None
        start, end = suggest_next_segment(last_end, task.info.duration_s)
        self._set_times(start, end)
        self.form_box.setTitle("Nouveau segment")
        self._update_segment_buttons()

    def _set_times(self, start: int, end: int) -> None:
        self.start_input.setValue(start)
        self.end_input.setValue(end)
        self.slider.blockSignals(True)
        self.slider.setValue((start, end))
        self.slider.blockSignals(False)
        self._validate()

    def _on_inputs_changed(self, _value: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(
            (self.start_input.value(), max(self.end_input.value(), self.start_input.value()))
        )
        self.slider.blockSignals(False)
        self._validate()

    def _on_slider(self, value: tuple[int, int]) -> None:
        start, end = (int(v) for v in value)
        self.start_input.setValue(start)
        self.end_input.setValue(end)
        self._validate()

    def _validate(self) -> bool:
        task = self._task
        if task is None or task.info is None:
            return False
        start, end = self.start_input.value(), self.end_input.value()
        try:
            validate_segment(start, end, task.info.duration_s)
        except InvalidSegmentError as exc:
            self.form_info.setText(exc.user_message)
            self.form_info.setStyleSheet("color: #c9302c;")
            self.add_btn.setEnabled(False)
            self.save_btn.setEnabled(False)
            return False
        self.form_info.setText(f"Durée : {format_time(end - start)}")
        self.form_info.setStyleSheet("")
        self.add_btn.setEnabled(True)
        self.save_btn.setEnabled(self._editing_segment is not None)
        return True

    def _on_enter(self) -> None:
        # La touche Entrée valide d'abord le texte saisi, puis ajoute/enregistre.
        self.start_input.commit_text()
        self.end_input.commit_text()
        if self._editing_segment:
            self._on_save()
        else:
            self._on_add()

    def _on_add(self) -> None:
        if self._task and self._validate():
            self.add_segment_requested.emit(
                self._task.id, self.start_input.value(), self.end_input.value()
            )

    def _on_save(self) -> None:
        if self._task and self._editing_segment and self._validate():
            self.update_segment_requested.emit(
                self._task.id,
                self._editing_segment,
                self.start_input.value(),
                self.end_input.value(),
            )
            self._reset_form()

    def after_segment_added(self) -> None:
        self._reset_form()

    # ------------------------------------------------------------------ segments

    def _selected_segment_id(self) -> str | None:
        item = self.segment_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item and item.isSelected() else None

    def _on_segment_selected(self, *_args: object) -> None:
        segment_id = self._selected_segment_id()
        task = self._task
        segment = next((s for s in task.segments if s.id == segment_id), None) if task else None
        if segment is not None and segment.status is SegmentStatus.PENDING:
            self._editing_segment = segment.id
            self.form_box.setTitle(f"Modifier le segment #{segment.number:03d}")
            self._set_times(segment.start_s, segment.end_s)
        elif self._editing_segment is not None:
            self._editing_segment = None
            self.form_box.setTitle("Nouveau segment")
        self._update_segment_buttons()
        self._validate()

    def _update_segment_buttons(self) -> None:
        task, segment_id = self._task, self._selected_segment_id()
        segment = next((s for s in task.segments if s.id == segment_id), None) if task else None
        self.remove_segment_btn.setEnabled(
            segment is not None and segment.status is not SegmentStatus.PROCESSING
        )
        self.cancel_segment_btn.setEnabled(
            segment is not None
            and segment.status in (SegmentStatus.PENDING, SegmentStatus.PROCESSING)
        )
        self.save_btn.setEnabled(self._editing_segment is not None)

    def _on_remove_segment(self) -> None:
        if self._task and (segment_id := self._selected_segment_id()):
            self.remove_segment_requested.emit(self._task.id, segment_id)

    def _on_cancel_segment(self) -> None:
        if self._task and (segment_id := self._selected_segment_id()):
            self.cancel_segment_requested.emit(self._task.id, segment_id)

    # ------------------------------------------------------------------ divers

    def _on_mode(self, mode: OutputMode) -> None:
        if self._task and self._task.mode is not mode:
            self.mode_change_requested.emit(self._task.id, mode)

    def _emit_task(self, signal: Signal) -> None:
        if self._task:
            signal.emit(self._task.id)

    def _set_form_enabled(self, enabled: bool) -> None:
        self.form_box.setEnabled(enabled)
