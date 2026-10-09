"""Theme palettes (``wcl_app.themes``): every mode and class theme keeps text readable to WCAG AA."""

import colorsys

import pytest
from wcl_app.themes import (
    AA_GRAPHICS,
    AA_TEXT,
    CLASS_COLORS,
    MODES,
    SURFACES,
    TEXT_TOKENS,
    VANILLA_CLASSES,
    build_palette,
    class_for,
    contrast,
    ensure_contrast,
    luminance,
)

THEMES = [(mode, wow_class) for mode in MODES for wow_class in (None, *VANILLA_CLASSES)]


def _hue(color: str) -> float:
    rgb = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(*rgb)[0]


def _ids(theme):
    mode, wow_class = theme
    return f"{wow_class or 'classic'}-{mode}"


@pytest.fixture(params=THEMES, ids=_ids)
def palette(request):
    return build_palette(*request.param)


class TestContrast:
    def test_black_on_white_is_the_maximum_ratio(self):
        assert contrast("#000000", "#ffffff") == pytest.approx(21.0)
        assert contrast("#fff", "#ffffff") == pytest.approx(1.0)
        assert luminance("#000") == 0.0 and luminance("#ffffff") == pytest.approx(1.0)

    def test_a_colour_that_passes_is_left_alone(self):
        assert ensure_contrast("#ffffff", ["#000000"], AA_TEXT) == "#ffffff"

    def test_a_failing_colour_lightens_on_dark_and_darkens_on_light(self):
        lifted = ensure_contrast("#0070dd", ["#22222a"], AA_TEXT)
        dropped = ensure_contrast("#1eff00", ["#ffffff"], AA_TEXT)
        assert contrast(lifted, "#22222a") >= AA_TEXT and luminance(lifted) > luminance("#0070dd")
        assert contrast(dropped, "#ffffff") >= AA_TEXT and luminance(dropped) < luminance("#1eff00")

    def test_an_unreachable_ratio_ends_at_black_or_white(self):
        assert ensure_contrast("#777777", ["#ffffff"], 22) == "#000000"
        assert ensure_contrast("#777777", ["#000000"], 22) == "#ffffff"

    def test_a_malformed_colour_is_refused(self):
        with pytest.raises(ValueError, match="not a #rgb"):
            luminance("#12345")


class TestEveryPalette:
    def test_every_text_colour_meets_aa_on_every_surface(self, palette):
        failures = [
            f"{token} {palette.colors[token]} on {surface} {palette.colors[surface]}"
            for token in TEXT_TOKENS
            for surface in SURFACES
            if contrast(palette.colors[token], palette.colors[surface]) < AA_TEXT
        ]
        assert failures == []

    def test_button_text_meets_aa_on_its_button(self, palette):
        c = palette.colors
        assert contrast(c["on_accent"], c["accent"]) >= AA_TEXT
        assert contrast(c["on_accent"], c["accent_hover"]) >= AA_TEXT
        assert contrast(c["on_danger"], c["danger"]) >= AA_TEXT
        assert contrast(c["on_danger"], c["danger_hover"]) >= AA_TEXT

    def test_class_names_are_readable_on_every_surface(self, palette):
        assert set(palette.class_colors) == set(VANILLA_CLASSES)
        for color in palette.class_colors.values():
            assert min(contrast(color, palette.colors[s]) for s in SURFACES) >= AA_TEXT

    def test_chart_series_stand_out_from_the_chart_background(self, palette):
        assert len(palette.series) == 10
        for color in palette.series:
            assert contrast(color, palette.colors["bg_card"]) >= AA_GRAPHICS

    def test_surfaces_follow_the_mode(self, palette):
        page = luminance(palette.colors["bg_dark"])
        assert page < 0.05 if palette.mode == "dark" else page > 0.8


class TestClassThemes:
    def test_the_classic_dark_theme_keeps_the_original_look(self):
        c = build_palette("dark").colors
        assert (c["bg_dark"], c["bg_card"], c["accent"], c["text"], c["text_gold"]) == (
            "#121214",
            "#22222a",
            "#c9a42c",
            "#e0e0e0",
            "#ffd100",
        )
        assert build_palette().name == "Classic dark"

    @pytest.mark.parametrize("wow_class", VANILLA_CLASSES)
    def test_a_dark_class_theme_is_led_by_its_class_colour(self, wow_class):
        palette = build_palette("dark", wow_class)
        accent, class_color = palette.colors["accent"], CLASS_COLORS[wow_class]
        assert palette.name == f"{wow_class} dark"
        # The class colour itself, or the same hue made lighter until it reads on dark surfaces (Shaman blue).
        assert accent.lower() == class_color.lower() or abs(_hue(accent) - _hue(class_color)) < 0.02

    def test_class_themes_differ_from_each_other(self):
        backgrounds = {build_palette("dark", c).colors["bg_card"] for c in VANILLA_CLASSES}
        accents = {build_palette("light", c).colors["accent"] for c in VANILLA_CLASSES}
        assert len(backgrounds) == len(accents) == len(VANILLA_CLASSES)

    def test_pale_classes_keep_a_readable_accent_on_light_surfaces(self):
        priest = build_palette("light", "Priest").colors
        assert priest["accent"] == "#7a5c12"  # holy gold: white cannot carry text on light surfaces
        assert priest["on_accent"] == "#ffffff"

    def test_only_vanilla_classes_and_known_modes_are_accepted(self):
        with pytest.raises(ValueError, match="not a vanilla class"):
            build_palette("dark", "Death Knight")
        with pytest.raises(ValueError, match="Unknown theme mode"):
            build_palette("sepia")  # type: ignore[arg-type]

    def test_class_names_match_whatever_their_case(self):
        assert class_for("warlock") == "Warlock"
        assert class_for(" MAGE ") == "Mage"
        assert class_for("Monk") is None and class_for(None) is None
