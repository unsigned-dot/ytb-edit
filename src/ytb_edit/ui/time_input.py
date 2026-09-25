"""Champ de saisie d'un temps avec boutons −10 / −1 / +1 / +10 s.

Clavier dans le champ : ↑/↓ = ±1 s, Maj = ±10 s, Ctrl = ±60 s ; molette = ±1 s
(Maj : ±10 s). Saisies acceptées : ``3:20``, ``320``, ``3m20s``, ``1:02:03``…
"""

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QToolButton, QWidget

from ytb_edit.core.errors import InvalidTimecodeError
from ytb_edit.core.segments import shift_time
from ytb_edit.core.timecode import format_time, parse_time

STEPS = (-10, -1, 1, 10)
_INVALID_STYLE = "QLineEdit { border: 1px solid #d9534f; background: #fdecea; }"


class TimeInput(QWidget):
    valueChanged = Signal(int)

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = 0
        self._maximum: int | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        caption = QLabel(label)
        caption.setMinimumWidth(40)
        layout.addWidget(caption)

        self.edit = QLineEdit(format_time(0))
        self.edit.setFixedWidth(80)
        self.edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit.setToolTip("Ex. : 3:20, 320, 1:02:03 — ↑/↓ ±1 s, Maj ±10 s, Ctrl ±60 s")
        self.edit.editingFinished.connect(self.commit_text)
        self.edit.textEdited.connect(lambda _: self.edit.setStyleSheet(""))
        self.edit.installEventFilter(self)
        layout.addWidget(self.edit)

        for step in STEPS:
            button = QToolButton()
            button.setText(f"{step:+d} s".replace("-", "−"))
            button.setAutoRaise(False)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _=False, s=step: self.shift(s))
            layout.addWidget(button)
        layout.addStretch(1)

    def value(self) -> int:
        return self._value

    def setValue(self, seconds: int, *, notify: bool = False) -> None:
        seconds = shift_time(seconds, 0, self._maximum)
        changed = seconds != self._value
        self._value = seconds
        self.edit.setText(format_time(seconds))
        self.edit.setStyleSheet("")
        if changed and notify:
            self.valueChanged.emit(seconds)

    def setMaximum(self, seconds: int | None) -> None:
        self._maximum = seconds

    def shift(self, delta: int) -> None:
        self.setValue(shift_time(self._value, delta, self._maximum), notify=True)

    def has_valid_text(self) -> bool:
        try:
            parse_time(self.edit.text())
            return True
        except InvalidTimecodeError:
            return False

    def commit_text(self) -> None:
        try:
            seconds = parse_time(self.edit.text())
        except InvalidTimecodeError as exc:
            self.edit.setStyleSheet(_INVALID_STYLE)
            self.edit.setToolTip(exc.user_message)
            return
        self.edit.setToolTip("Ex. : 3:20, 320, 1:02:03 — ↑/↓ ±1 s, Maj ±10 s, Ctrl ±60 s")
        if self._maximum is not None and seconds > self._maximum:
            seconds = self._maximum
        self.setValue(seconds, notify=True)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self.edit:
            if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
                if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                    self.commit_text()
                    sign = 1 if event.key() == Qt.Key.Key_Up else -1
                    self.shift(sign * _step_for(event.modifiers()))
                    return True
            elif event.type() == QEvent.Type.Wheel and isinstance(event, QWheelEvent):
                delta = event.angleDelta().y() or event.angleDelta().x()
                if delta:
                    self.commit_text()
                    self.shift((1 if delta > 0 else -1) * _step_for(event.modifiers()))
                return True
        return super().eventFilter(watched, event)


def _step_for(modifiers: Qt.KeyboardModifier) -> int:
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        return 60
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        return 10
    return 1
