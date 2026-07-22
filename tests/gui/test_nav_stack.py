"""Tests for NavigationStack widget using pytest-qt."""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLabel, QWidget

from warcraftlogs_client.gui.nav_stack import NavigationStack


@pytest.mark.gui
class TestNavigationStack:
    def test_initial_depth_is_zero(self, qtbot):
        stack = NavigationStack()
        qtbot.addWidget(stack)
        assert stack.current_depth() == 0

    def test_push_increases_depth(self, qtbot):
        stack = NavigationStack()
        qtbot.addWidget(stack)

        page = QWidget()
        stack.addWidget(page)
        stack.set_base_count(1)

        w1 = QLabel("drill 1")
        stack.push_view(w1)
        assert stack.current_depth() == 1

        w2 = QLabel("drill 2")
        stack.push_view(w2)
        assert stack.current_depth() == 2

    def test_pop_decreases_depth(self, qtbot):
        stack = NavigationStack()
        qtbot.addWidget(stack)

        page = QWidget()
        stack.addWidget(page)
        stack.set_base_count(1)

        w1 = QLabel("drill 1")
        w2 = QLabel("drill 2")
        stack.push_view(w1)
        stack.push_view(w2)
        assert stack.current_depth() == 2

        stack.pop_view()
        assert stack.current_depth() == 1

        stack.pop_view()
        assert stack.current_depth() == 0

    def test_pop_on_empty_drill_stack_does_not_crash(self, qtbot):
        stack = NavigationStack()
        qtbot.addWidget(stack)

        # Should not raise any exception
        stack.pop_view()
        assert stack.current_depth() == 0

    def test_show_base_page_clears_drill_stack(self, qtbot):
        stack = NavigationStack()
        qtbot.addWidget(stack)

        base1 = QWidget()
        base2 = QWidget()
        stack.addWidget(base1)
        stack.addWidget(base2)
        stack.set_base_count(2)

        w1 = QLabel("drill 1")
        w2 = QLabel("drill 2")
        stack.push_view(w1)
        stack.push_view(w2)
        assert stack.current_depth() == 2

        stack.show_base_page(1)
        assert stack.current_depth() == 0
        assert stack.currentWidget() is base2

    def test_depth_changed_signal_emitted_on_push(self, qtbot):
        stack = NavigationStack()
        qtbot.addWidget(stack)

        base = QWidget()
        stack.addWidget(base)
        stack.set_base_count(1)

        w = QLabel("drill")
        with qtbot.waitSignal(stack.depth_changed, timeout=1000) as blocker:
            stack.push_view(w)
        assert blocker.args == [1]

    def test_depth_changed_signal_emitted_on_pop(self, qtbot):
        stack = NavigationStack()
        qtbot.addWidget(stack)

        base = QWidget()
        stack.addWidget(base)
        stack.set_base_count(1)

        w = QLabel("drill")
        stack.push_view(w)

        with qtbot.waitSignal(stack.depth_changed, timeout=1000) as blocker:
            stack.pop_view()
        assert blocker.args == [0]

    def test_push_shows_pushed_widget(self, qtbot):
        stack = NavigationStack()
        qtbot.addWidget(stack)

        base = QWidget()
        stack.addWidget(base)
        stack.set_base_count(1)
        stack.show_base_page(0)

        w = QLabel("drill")
        stack.push_view(w)
        assert stack.currentWidget() is w

    def test_pop_shows_previous_drill_or_base(self, qtbot):
        stack = NavigationStack()
        qtbot.addWidget(stack)

        base = QWidget()
        stack.addWidget(base)
        stack.set_base_count(1)
        stack.show_base_page(0)

        w1 = QLabel("drill 1")
        w2 = QLabel("drill 2")
        stack.push_view(w1)
        stack.push_view(w2)

        stack.pop_view()
        assert stack.currentWidget() is w1

        stack.pop_view()
        assert stack.currentWidget() is base
