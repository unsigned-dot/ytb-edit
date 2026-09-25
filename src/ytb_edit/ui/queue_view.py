"""Arbre de la file : une ligne par vidéo, une sous-ligne par segment."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHeaderView, QTreeWidget, QTreeWidgetItem, QWidget

from ytb_edit.core.models import SegmentStatus, TaskStatus, VideoTask
from ytb_edit.ui.labels import SEGMENT_LABELS, segment_text, segments_progress, task_status_text

_ID = Qt.ItemDataRole.UserRole


class QueueView(QTreeWidget):
    task_selected = Signal(object)  # id de tâche ou None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderLabels(["Vidéo / segment", "État", "Progression"])
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        header = self.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(False)
        self._items: dict[str, QTreeWidgetItem] = {}
        self.currentItemChanged.connect(self._on_current_changed)

    def update_task(self, task: VideoTask) -> None:
        item = self._items.get(task.id)
        if item is None:
            item = QTreeWidgetItem([task.title, "", ""])
            item.setData(0, _ID, task.id)
            self.addTopLevelItem(item)
            self._items[task.id] = item
            if self.currentItem() is None:
                self.setCurrentItem(item)
        item.setText(0, task.title)
        item.setToolTip(0, task.url)
        item.setText(1, task_status_text(task))
        item.setToolTip(1, task.error or "")
        color = Qt.GlobalColor.red if task.status is TaskStatus.FAILED else None
        item.setForeground(1, color or self.palette().text().color())
        if task.status is TaskStatus.DOWNLOADING:
            item.setText(2, f"{task.download_progress:.0%}")
        else:
            item.setText(2, segments_progress(task))

        expanded = item.isExpanded() or item.childCount() == 0
        item.takeChildren()
        for segment in task.segments:
            child = QTreeWidgetItem([segment_text(segment), SEGMENT_LABELS[segment.status], ""])
            child.setData(0, _ID, task.id)
            if segment.error:
                child.setToolTip(1, segment.error)
            if segment.status is SegmentStatus.FAILED:
                child.setForeground(1, Qt.GlobalColor.red)
            if segment.output_path:
                child.setToolTip(0, str(segment.output_path))
            item.addChild(child)
        item.setExpanded(expanded)

    def set_progress(self, task_id: str, text: str) -> None:
        if item := self._items.get(task_id):
            item.setText(2, text)

    def remove_task(self, task_id: str) -> None:
        item = self._items.pop(task_id, None)
        if item is not None:
            self.takeTopLevelItem(self.indexOfTopLevelItem(item))

    def select_task(self, task_id: str) -> None:
        if item := self._items.get(task_id):
            self.setCurrentItem(item)

    def _on_current_changed(self, current: QTreeWidgetItem | None, _previous: object) -> None:
        self.task_selected.emit(current.data(0, _ID) if current else None)
