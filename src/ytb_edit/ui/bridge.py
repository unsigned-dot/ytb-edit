"""Pont entre le moteur (threads Python) et l'interface (thread Qt).

Un signal Qt émis depuis un autre thread est automatiquement remis dans le
thread de l'interface : les widgets ne sont jamais touchés depuis un worker.
"""

from PySide6.QtCore import QObject, Signal

from ytb_edit.core.events import Event


class EngineBridge(QObject):
    event_received = Signal(object)

    def emit(self, event: Event) -> None:
        self.event_received.emit(event)
