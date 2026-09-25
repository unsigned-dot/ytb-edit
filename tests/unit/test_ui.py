"""Quelques tests de l'interface (pytest-qt), avec le vrai moteur et de faux services."""

import pytest
from PySide6.QtCore import Qt

from ytb_edit.core.engine import Engine, EngineConfig
from ytb_edit.core.models import OutputMode, SegmentStatus, TaskStatus
from ytb_edit.services.cache import SourceCache
from ytb_edit.settings import AppSettings
from ytb_edit.ui.bridge import EngineBridge
from ytb_edit.ui.main_window import MainWindow
from ytb_edit.ui.time_input import TimeInput

from .test_engine import ID_A, FakeMedia, make_info


def test_time_input_buttons_and_keyboard(qtbot):
    widget = TimeInput("Début")
    qtbot.addWidget(widget)
    widget.setMaximum(600)
    widget.setValue(200)
    received = []
    widget.valueChanged.connect(received.append)

    widget.shift(10)
    assert widget.value() == 210 and widget.edit.text() == "03:30"
    qtbot.keyClick(widget.edit, Qt.Key.Key_Down)
    assert widget.value() == 209
    qtbot.keyClick(widget.edit, Qt.Key.Key_Up, Qt.KeyboardModifier.ShiftModifier)
    assert widget.value() == 219
    widget.shift(-1000)
    assert widget.value() == 0
    widget.shift(10_000)
    assert widget.value() == 600
    assert received == [210, 209, 219, 0, 600]


def test_time_input_text_entry(qtbot):
    widget = TimeInput("Fin")
    qtbot.addWidget(widget)
    widget.edit.setText("320")
    widget.commit_text()
    assert widget.value() == 200 and widget.edit.text() == "03:20"
    widget.edit.setText("n'importe quoi")
    widget.commit_text()
    assert widget.value() == 200  # valeur précédente conservée
    assert "border" in widget.edit.styleSheet()


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr("ytb_edit.ui.main_window.save_settings", lambda s: None)
    media = FakeMedia()
    media.infos = {ID_A: make_info(ID_A, "Vidéo A")}
    bridge = EngineBridge()
    engine = Engine(
        media,
        SourceCache(tmp_path / "cache"),
        bridge.emit,
        EngineConfig(output_dir=tmp_path / "clips"),
    )
    engine.start_workers()
    settings = AppSettings(output_dir=str(tmp_path / "clips"))
    win = MainWindow(engine, bridge, settings, ffmpeg_ok=True, js_runtime_ok=True)
    qtbot.addWidget(win)
    yield win, engine, tmp_path / "clips"
    engine.shutdown(timeout=2)


def test_full_flow_through_the_window(qtbot, window):
    win, engine, clips = window
    win.url_edit.setText(f"https://youtu.be/{ID_A}")
    win._add_url()
    qtbot.waitUntil(lambda: win.panel.form_box.isEnabled(), timeout=5000)
    assert win.panel.title.text() == "Vidéo A"

    # Première suggestion : 00:00 → 00:30. On ajuste la fin avec les boutons.
    assert (win.panel.start_input.value(), win.panel.end_input.value()) == (0, 30)
    win.panel.end_input.shift(-10)
    assert win.panel.slider.value() == (0, 20)
    win.panel.add_btn.click()
    qtbot.waitUntil(lambda: win.panel.segment_list.count() == 1, timeout=3000)
    # La saisie suivante enchaîne sur le segment précédent.
    assert win.panel.start_input.value() == 20

    win.start_btn.click()
    qtbot.waitUntil(lambda: engine.snapshot()[0].status is TaskStatus.COMPLETED, timeout=5000)
    assert (clips / "Vidéo A" / "clip_001_00m00s-00m20s.mp4").exists()
    qtbot.waitUntil(lambda: "Segments 1/1" in win.stats_label.text(), timeout=3000)
    assert win.global_bar.value() == 1000


def test_invalid_url_shows_message(qtbot, window):
    win, engine, _ = window
    win.url_edit.setText("https://example.com")
    win._add_url()
    assert "YouTube" in win.url_error.text()
    assert engine.snapshot() == []


def test_invalid_segment_disables_add_button(qtbot, window):
    win, *_ = window
    win.url_edit.setText(f"https://youtu.be/{ID_A}")
    win._add_url()
    qtbot.waitUntil(lambda: win.panel.form_box.isEnabled(), timeout=5000)
    win.panel.start_input.setValue(100, notify=True)
    win.panel.end_input.setValue(50, notify=True)
    assert not win.panel.add_btn.isEnabled()
    assert "après le début" in win.panel.form_info.text()


def test_mode_buttons_reflect_task(qtbot, window):
    win, engine, _ = window
    win.mode_combo.setCurrentIndex(win.mode_combo.findData(OutputMode.AUDIO_ONLY.value))
    win.url_edit.setText(f"https://youtu.be/{ID_A}")
    win._add_url()
    qtbot.waitUntil(lambda: win.panel.form_box.isEnabled(), timeout=5000)
    assert win.panel.mode_buttons[OutputMode.AUDIO_ONLY].isChecked()
    win.panel.mode_buttons[OutputMode.VIDEO_ONLY].click()
    qtbot.waitUntil(lambda: engine.snapshot()[0].mode is OutputMode.VIDEO_ONLY, timeout=2000)
    assert all(s.status is SegmentStatus.PENDING for s in engine.snapshot()[0].segments)
