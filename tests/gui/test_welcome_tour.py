"""The welcome tour overlay: steps, what it points at, where its card sits, and how it ends."""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from warcraftlogs_client.gui.command_palette import COMMANDS
from warcraftlogs_client.gui.welcome_tour import (
    BACK,
    DONE,
    MARGIN,
    NEXT,
    SKIP,
    START,
    WELCOME_STEPS,
    TourCopy,
    TourStep,
    WelcomeTour,
    card_position,
)

BOUNDS = QRect(0, 0, 1000, 800)
CARD = QRect(0, 0, 300, 200)


def _host(qtbot):
    host = QWidget()
    host.resize(1000, 800)
    layout = QHBoxLayout(host)
    host.left = QPushButton("Left")
    host.right = QPushButton("Right")
    layout.addWidget(host.left)
    layout.addWidget(host.right)
    qtbot.addWidget(host)
    host.show()
    qtbot.waitExposed(host)
    return host


def _tour(qtbot, host, steps):
    tour = WelcomeTour(host, steps)
    ended = []
    tour.finished.connect(ended.append)
    tour.start()
    return tour, ended


def _steps(host, opened=None):
    opened = [] if opened is None else opened
    return [
        TourStep(TourCopy("hello", "Hello", "First"), prepare=lambda: opened.append("hello")),
        TourStep(TourCopy("left", "Left", "Second"), target=lambda: host.left, prepare=lambda: opened.append("left")),
        TourStep(TourCopy("both", "Both", "Third"), target=lambda: [host.left, host.right]),
    ]


@pytest.mark.gui
class TestWelcomeTour:
    def test_starts_on_the_first_step_covering_the_window(self, qtbot):
        host = _host(qtbot)
        opened = []
        tour, _ = _tour(qtbot, host, _steps(host, opened))
        assert tour.isVisible() and tour.geometry() == host.rect()
        assert tour.title.text() == "Hello" and tour.counter.text() == "1 of 3"
        assert tour.next_button.text() == START and tour.back_button.isHidden()
        assert tour.skip_button.text() == SKIP and not tour.skip_button.isHidden()
        assert opened == ["hello"] and tour.target_rect() is None

    def test_next_opens_the_step_and_points_at_its_widget(self, qtbot):
        host = _host(qtbot)
        opened = []
        tour, _ = _tour(qtbot, host, _steps(host, opened))
        tour.next_button.click()
        assert opened == ["hello", "left"] and tour.index == 1
        assert tour.next_button.text() == NEXT and tour.back_button.text() == BACK
        assert not tour.back_button.isHidden()
        hole = tour.target_rect()
        assert hole is not None and hole.contains(QRect(host.left.mapTo(host, QPoint(0, 0)), host.left.size()))
        assert not hole.intersects(QRect(host.right.mapTo(host, QPoint(0, 0)), host.right.size()))
        assert not tour.card.geometry().intersects(hole)

    def test_a_step_can_point_at_several_widgets(self, qtbot):
        host = _host(qtbot)
        tour, _ = _tour(qtbot, host, _steps(host))
        tour.next_button.click()
        tour.next_button.click()
        hole = tour.target_rect()
        for widget in (host.left, host.right):
            assert hole.contains(QRect(widget.mapTo(host, QPoint(0, 0)), widget.size()))

    def test_a_hidden_target_leaves_the_card_in_the_middle(self, qtbot):
        host = _host(qtbot)
        host.left.hide()
        tour, _ = _tour(qtbot, host, _steps(host))
        tour.next_button.click()
        assert tour.target_rect() is None

    def test_back_returns_to_the_previous_step(self, qtbot):
        host = _host(qtbot)
        tour, _ = _tour(qtbot, host, _steps(host))
        tour.next_button.click()
        tour.back_button.click()
        assert tour.index == 0 and tour.title.text() == "Hello"
        tour.back()  # already on the first step
        assert tour.index == 0

    def test_the_last_step_finishes_the_tour(self, qtbot):
        host = _host(qtbot)
        tour, ended = _tour(qtbot, host, _steps(host))
        tour.next_button.click()
        tour.next_button.click()
        assert tour.next_button.text() == DONE and tour.skip_button.isHidden()
        tour.next_button.click()
        assert ended == [True] and not tour.isVisible()

    def test_skip_ends_it_early(self, qtbot):
        host = _host(qtbot)
        tour, ended = _tour(qtbot, host, _steps(host))
        tour.skip_button.click()
        assert ended == [False] and not tour.isVisible()

    def test_the_keyboard_drives_it(self, qtbot):
        host = _host(qtbot)
        tour, ended = _tour(qtbot, host, _steps(host))
        qtbot.keyClick(tour, Qt.Key.Key_Right)
        assert tour.index == 1
        qtbot.keyClick(tour, Qt.Key.Key_Left)
        assert tour.index == 0
        qtbot.keyClick(tour, Qt.Key.Key_Return)
        assert tour.index == 1
        qtbot.keyClick(tour, Qt.Key.Key_Escape)
        assert ended == [False]

    def test_clicks_do_not_reach_the_window_underneath(self, qtbot):
        host = _host(qtbot)
        clicked = []
        host.right.clicked.connect(lambda: clicked.append(True))
        tour, _ = _tour(qtbot, host, _steps(host))
        qtbot.mouseClick(tour, Qt.MouseButton.LeftButton, pos=host.right.geometry().center())
        assert clicked == []

    def test_the_tour_follows_the_window_when_it_resizes(self, qtbot):
        host = _host(qtbot)
        tour, _ = _tour(qtbot, host, _steps(host))
        host.resize(1200, 900)
        qtbot.waitUntil(lambda: tour.geometry() == host.rect())
        assert host.rect().contains(tour.card.geometry())

    def test_a_tour_needs_steps(self, qtbot):
        host = _host(qtbot)
        with pytest.raises(ValueError, match="at least one step"):
            WelcomeTour(host, [])


class TestCardPosition:
    def test_no_target_centres_the_card(self):
        assert card_position(None, CARD, BOUNDS) == QPoint(350, 300)

    def test_below_a_target_near_the_top(self):
        point = card_position(QRect(400, 50, 200, 40), CARD, BOUNDS)
        assert point.y() > 90 and point.x() == 350

    def test_above_a_target_near_the_bottom(self):
        point = card_position(QRect(400, 700, 200, 40), CARD, BOUNDS)
        assert point.y() + CARD.height() < 700

    def test_beside_a_tall_target(self):
        point = card_position(QRect(10, 10, 180, 780), CARD, BOUNDS)
        assert point.x() > 190

    def test_left_of_a_tall_target_on_the_right(self):
        point = card_position(QRect(810, 10, 180, 780), CARD, BOUNDS)
        assert point.x() + CARD.width() < 810

    def test_inside_a_target_that_fills_the_window(self):
        point = card_position(QRect(0, 0, 1000, 800), CARD, BOUNDS)
        assert BOUNDS.adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN).contains(QRect(point, CARD.size()))

    def test_the_card_stays_inside_the_window(self):
        point = card_position(QRect(980, 10, 15, 20), CARD, BOUNDS)
        assert BOUNDS.adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN).contains(QRect(point, CARD.size()))


class TestWelcomeSteps:
    def test_each_step_has_a_distinct_key_and_words(self):
        keys = [step.key for step in WELCOME_STEPS]
        assert len(keys) == len(set(keys))
        assert all(step.title and step.body for step in WELCOME_STEPS)

    def test_it_covers_the_features_a_new_user_needs(self):
        keys = {step.key for step in WELCOME_STEPS}
        assert {"welcome", "settings", "download", "character", "profile"} <= keys
        assert WELCOME_STEPS[0].key == "welcome"

    def test_the_command_palette_can_start_it(self):
        assert "tour" in {command["key"] for command in COMMANDS}
