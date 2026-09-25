"""Vérifie que le squelette du projet est correctement installé."""

import logging
from importlib.metadata import version

import ytb_edit
from ytb_edit import paths
from ytb_edit.logging_setup import setup_logging


def test_package_version_matches_metadata():
    assert ytb_edit.__version__ == version("ytb-edit")


def test_app_paths_are_distinct_and_named_after_app():
    dirs = [paths.config_dir(), paths.log_dir(), paths.default_cache_dir()]
    assert all(ytb_edit.APP_NAME in str(d) for d in dirs)
    assert len(set(dirs)) == 3


def test_setup_logging_writes_to_file(tmp_path):
    log_file = setup_logging(tmp_path / "logs")
    logging.getLogger("ytb_edit.test").info("bonjour")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert "bonjour" in log_file.read_text(encoding="utf-8")


def test_setup_logging_is_idempotent(tmp_path):
    setup_logging(tmp_path)
    setup_logging(tmp_path)
    assert len(logging.getLogger().handlers) == 1


def test_qt_is_available(qtbot):
    from PySide6.QtWidgets import QLabel

    label = QLabel("ok")
    qtbot.addWidget(label)
    assert label.text() == "ok"
