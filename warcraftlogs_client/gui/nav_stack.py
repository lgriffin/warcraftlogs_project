"""
Navigation stack for drill-down page navigation.

Wraps QStackedWidget to support pushing/popping views on top of
the base sidebar pages. Emits signals for back-button visibility.
"""

from PySide6.QtWidgets import QStackedWidget, QWidget
from PySide6.QtCore import Signal


class NavigationStack(QStackedWidget):

    depth_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._base_count = 0
        self._drill_stack: list[QWidget] = []

    def set_base_count(self, count: int):
        self._base_count = count

    def show_base_page(self, index: int):
        self._clear_drill_stack()
        self.setCurrentIndex(index)

    def push_view(self, widget: QWidget):
        self.addWidget(widget)
        self._drill_stack.append(widget)
        self.setCurrentWidget(widget)
        self.depth_changed.emit(len(self._drill_stack))

    def pop_view(self):
        if not self._drill_stack:
            return
        widget = self._drill_stack.pop()
        self.removeWidget(widget)
        widget.deleteLater()
        if self._drill_stack:
            self.setCurrentWidget(self._drill_stack[-1])
        self.depth_changed.emit(len(self._drill_stack))

    def current_depth(self) -> int:
        return len(self._drill_stack)

    def _clear_drill_stack(self):
        while self._drill_stack:
            widget = self._drill_stack.pop()
            self.removeWidget(widget)
            widget.deleteLater()
        self.depth_changed.emit(0)
