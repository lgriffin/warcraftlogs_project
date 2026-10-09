"""The Appearance section of Settings, and switching the palette every widget draws with."""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from warcraftlogs_client.services.appearance import FOLLOW_MAIN, NO_CLASS, MemoryAppearanceStore

from warcraftlogs_client.gui import styles
from warcraftlogs_client.gui.app import apply_theme
from warcraftlogs_client.gui.appearance_panel import AppearancePanel, follow_main_text
from warcraftlogs_client.gui.charts import SERIES_COLORS
from warcraftlogs_client.gui.table_models import _class_color
from warcraftlogs_client.services import Appearance, AppearanceService, build_palette


@pytest.fixture(autouse=True)
def classic_palette_after():
    yield
    styles.apply_palette(build_palette())
    QApplication.instance().setPalette(styles.qt_palette())
    QApplication.instance().setStyleSheet(styles.app_styles())


def _panel(qtbot, store=None, main_class="Mage"):
    service = AppearanceService(store or MemoryAppearanceStore(), main_class=lambda: main_class)
    panel = AppearancePanel(service)
    qtbot.addWidget(panel)
    return panel


class TestAppearancePanel:
    def test_starts_on_the_saved_choice(self, qtbot):
        store = MemoryAppearanceStore({"local": Appearance("light", "Warlock")})
        panel = _panel(qtbot, store)
        assert panel.mode.currentData() == "light"
        assert panel.class_theme.currentData() == "Warlock"
        assert panel.chosen() == Appearance("light", "Warlock")

    def test_offers_following_the_main_none_and_the_nine_classes(self, qtbot):
        panel = _panel(qtbot)
        items = [panel.class_theme.itemData(i) for i in range(panel.class_theme.count())]
        assert items[:2] == [FOLLOW_MAIN, NO_CLASS] and len(items) == 11
        assert panel.class_theme.itemText(0) == follow_main_text("Mage") == "Match my main (Mage)"
        assert follow_main_text(None) == "Match my main (not seen in a raid yet)"

    def test_the_preview_redraws_in_the_chosen_palette(self, qtbot):
        panel = _panel(qtbot)
        assert build_palette("dark", "Mage").colors["accent"] in panel.preview.button.styleSheet()
        panel.class_theme.setCurrentIndex(panel.class_theme.findData("Druid"))
        panel.mode.setCurrentIndex(panel.mode.findData("light"))
        assert build_palette("light", "Druid").colors["accent"] in panel.preview.button.styleSheet()
        assert "forest" in panel.flavour.text()
        panel.class_theme.setCurrentIndex(panel.class_theme.findData(NO_CLASS))
        assert panel.flavour.text() == "The original WoW-gold look"

    def test_apply_saves_and_announces_the_theme(self, qtbot):
        store = MemoryAppearanceStore()
        panel = _panel(qtbot, store)
        panel.class_theme.setCurrentIndex(panel.class_theme.findData("Paladin"))
        with qtbot.waitSignal(panel.theme_applied) as applied, qtbot.waitSignal(panel.status_message) as status:
            panel.apply()
        assert store.load("local") == Appearance("dark", "Paladin")
        assert applied.args[0].wow_class == "Paladin"
        assert status.args[0] == "Theme: Paladin dark"

    def test_a_failed_save_is_reported_not_applied(self, qtbot):
        class Unwritable(MemoryAppearanceStore):
            def save(self, owner, appearance):
                raise OSError("read-only")

        panel = _panel(qtbot, Unwritable())
        applied = []
        panel.theme_applied.connect(applied.append)
        with qtbot.waitSignal(panel.status_message) as status:
            panel.apply()
        assert "read-only" in status.args[0] and applied == []


class TestApplyTheme:
    def test_new_widgets_draw_in_the_applied_palette(self, qtbot):
        theme = AppearanceService(MemoryAppearanceStore()).theme(Appearance("light", "Shaman"))
        apply_theme(QApplication.instance(), theme)
        colors = theme.palette.colors
        assert styles.COLORS["bg_card"] == colors["bg_card"]
        assert colors["accent"] in styles.common_styles()
        assert colors["on_accent"] in styles.common_styles()
        assert SERIES_COLORS[0].name() == theme.palette.series[0].lower()
        assert len(SERIES_COLORS) == 10 and len(SERIES_COLORS[:2]) == 2
        assert _class_color("Rogue").name() == theme.palette.class_colors["Rogue"].lower()
        assert styles.qt_palette().window().color().name() == colors["bg_dark"]
        assert styles.active_palette() is theme.palette
