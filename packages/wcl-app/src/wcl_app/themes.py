"""Colour palettes: dark and light, each plain or styled after one of the nine vanilla WoW classes.

A palette is a set of named colour tokens (``bg_card``, ``text``, ``accent``...) that every frontend draws with, so the
desktop and the Toads Hub can share a theme. Class palettes are built from the class colour the game's UI uses, a
surface tint and a second accent that suit the class (fel green for Warlocks, holy gold for Paladins), then every text
colour is checked against every surface it can sit on and moved until it meets WCAG AA (4.5:1); chart series meet the
3:1 that graphics need. ``tests/test_themes.py`` holds every palette to that.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass, field
from typing import Literal

Mode = Literal["dark", "light"]
MODES: tuple[Mode, ...] = ("dark", "light")

AA_TEXT = 4.5  # WCAG AA for normal text
AA_GRAPHICS = 3.0  # WCAG AA for chart marks and other non-text graphics

# The class colours of the vanilla game UI (RAID_CLASS_COLORS), which tables and names have always used.
CLASS_COLORS: dict[str, str] = {
    "Druid": "#FF7D0A",
    "Hunter": "#ABD473",
    "Mage": "#69CCF0",
    "Paladin": "#F58CBA",
    "Priest": "#FFFFFF",
    "Rogue": "#FFF569",
    "Shaman": "#0070DE",
    "Warlock": "#9482C9",
    "Warrior": "#C79C6E",
}
VANILLA_CLASSES: tuple[str, ...] = tuple(CLASS_COLORS)

SURFACES = ("bg_dark", "bg_mid", "bg_card", "bg_input", "bg_hover")
# Tokens drawn as text on any surface; each must reach AA_TEXT against every one of SURFACES.
TEXT_TOKENS = (
    "text",
    "text_dim",
    "text_header",
    "text_gold",
    "accent",
    "purple",
    "success",
    "warning",
    "error",
    "info",
    "quality_common",
    "quality_uncommon",
    "quality_rare",
    "quality_epic",
    "quality_legendary",
    "quality_artifact",
)

_SEMANTIC = {
    "success": "#1eff00",
    "warning": "#ff8000",
    "error": "#e74c3c",
    "info": "#69CCF0",
    "quality_common": "#9d9d9d",
    "quality_uncommon": "#1eff00",
    "quality_rare": "#0070dd",
    "quality_epic": "#a335ee",
    "quality_legendary": "#ff8000",
    "quality_artifact": "#e268a8",
}
# Fills for destructive buttons, with white text on them in every theme.
_DANGER = {"danger": "#c0392b", "danger_hover": "#a93226", "on_danger": "#ffffff"}
_SERIES = (
    "#c9a42c",  # WoW gold
    "#69CCF0",  # Mage blue
    "#1eff00",  # Uncommon green
    "#ff8000",  # Legendary orange
    "#a335ee",  # Epic purple
    "#ABD473",  # Hunter green
    "#F58CBA",  # Paladin pink
    "#C79C6E",  # Warrior tan
    "#FFF569",  # Rogue yellow
    "#0070DE",  # Rare blue
)


@dataclass(frozen=True)
class ClassStyle:
    """What makes a class palette feel like the class."""

    name: str
    color: str  # the class colour; the palette's main accent
    tint: float  # hue of the surfaces, in degrees
    saturation: float  # how strongly the surfaces take that hue (HLS saturation)
    secondary: str  # the second accent
    flavour: str  # a few words on the look, for a theme picker
    light_accent: str | None = None  # accent on light surfaces, where the class colour is too pale to read


CLASS_STYLES: dict[str, ClassStyle] = {
    s.name: s
    for s in (
        ClassStyle("Druid", CLASS_COLORS["Druid"], 120, 0.22, "#6cc24a", "Feral orange on deep forest green"),
        ClassStyle("Hunter", CLASS_COLORS["Hunter"], 75, 0.20, "#c8a165", "Hunter green on olive and leather"),
        ClassStyle("Mage", CLASS_COLORS["Mage"], 222, 0.34, "#b48cff", "Frost blue and arcane violet on night sky"),
        ClassStyle("Paladin", CLASS_COLORS["Paladin"], 340, 0.16, "#f2c94c", "Paladin pink and holy gold"),
        ClassStyle("Priest", CLASS_COLORS["Priest"], 232, 0.14, "#f2d675", "Holy white and gold on silver", "#7a5c12"),
        ClassStyle("Rogue", CLASS_COLORS["Rogue"], 60, 0.06, "#8fd14f", "Rogue yellow and poison in the shadows"),
        ClassStyle("Shaman", CLASS_COLORS["Shaman"], 208, 0.32, "#3fd0c9", "Storm blue and totem teal"),
        ClassStyle("Warlock", CLASS_COLORS["Warlock"], 272, 0.28, "#7fd13b", "Shadow violet and fel green"),
        ClassStyle("Warrior", CLASS_COLORS["Warrior"], 22, 0.18, "#d0453a", "Leather tan and blood red on iron"),
    )
}

# The original hand-tuned dark look, kept exactly where it already met AA.
_CLASSIC_DARK = {
    "bg_dark": "#121214",
    "bg_mid": "#1a1a1f",
    "bg_card": "#22222a",
    "bg_input": "#2a2a35",
    "bg_hover": "#32323e",
    "accent": "#c9a42c",
    "accent_hover": "#dbb734",
    "accent_dim": "#8a7020",
    "purple": "#8b5cf6",
    "purple_hover": "#a78bfa",
    "text": "#e0e0e0",
    "text_dim": "#888892",
    "text_header": "#f5f5f5",
    "text_gold": "#ffd100",
    "border": "#2f2f3a",
    "border_accent": "#4a4535",
}
_CLASSIC_TINT = (232.0, 0.06)
_CLASSIC_ACCENT = "#c9a42c"

# Surface lightness, darkest page to brightest hover, per mode.
_SURFACE_LIGHTNESS: dict[Mode, dict[str, float]] = {
    "dark": {"bg_dark": 0.07, "bg_mid": 0.10, "bg_card": 0.13, "bg_input": 0.165, "bg_hover": 0.205, "border": 0.23},
    "light": {"bg_dark": 0.945, "bg_mid": 0.905, "bg_card": 0.985, "bg_input": 1.0, "bg_hover": 0.875, "border": 0.78},
}


# ── Colour arithmetic ──


def _rgb(color: str) -> tuple[float, float, float]:
    h = color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"'{color}' is not a #rgb or #rrggbb colour")
    return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255


def _hex(r: float, g: float, b: float) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in (r, g, b))


def _hls(color: str) -> tuple[float, float, float]:
    return colorsys.rgb_to_hls(*_rgb(color))


def _from_hls(hue: float, lightness: float, saturation: float) -> str:
    return _hex(*colorsys.hls_to_rgb(hue % 1.0, max(0.0, min(1.0, lightness)), max(0.0, min(1.0, saturation))))


def luminance(color: str) -> float:
    """WCAG relative luminance, 0 for black to 1 for white."""

    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two colours, 1 to 21."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def ensure_contrast(color: str, backgrounds: tuple[str, ...] | list[str], ratio: float) -> str:
    """``color`` with its lightness moved, hue kept, until it reaches ``ratio`` against every background.

    Light backgrounds darken it, dark ones lighten it. Unchanged when it already passes.
    """
    if min(contrast(color, bg) for bg in backgrounds) >= ratio:
        return color
    hue, lightness, saturation = _hls(color)
    darken = sum(luminance(bg) for bg in backgrounds) / len(backgrounds) > 0.18
    step = -0.01 if darken else 0.01
    candidate = color
    while 0.0 < lightness < 1.0:
        lightness += step
        candidate = _from_hls(hue, lightness, saturation)
        if min(contrast(candidate, bg) for bg in backgrounds) >= ratio:
            return candidate
    return "#000000" if darken else "#ffffff"


def _shift(color: str, amount: float) -> str:
    hue, lightness, saturation = _hls(color)
    return _from_hls(hue, lightness + amount, saturation)


def _mix(a: str, b: str, weight: float) -> str:
    """``weight`` of ``a`` blended with the rest of ``b``."""
    return _hex(*(x * weight + y * (1 - weight) for x, y in zip(_rgb(a), _rgb(b), strict=True)))


# ── Palettes ──


@dataclass(frozen=True)
class Palette:
    """Every colour a frontend draws with, for one mode and class (None for the plain theme)."""

    mode: Mode
    wow_class: str | None
    colors: dict[str, str] = field(default_factory=dict)
    class_colors: dict[str, str] = field(default_factory=dict)  # each class's name colour, readable here
    series: tuple[str, ...] = ()  # chart series colours, in order

    @property
    def name(self) -> str:
        return f"{self.wow_class or 'Classic'} {self.mode}"


def _surfaces(mode: Mode, hue: float, saturation: float) -> dict[str, str]:
    h = hue / 360
    sat = saturation if mode == "dark" else min(saturation * 1.4, 0.45)
    return {token: _from_hls(h, lightness, sat) for token, lightness in _SURFACE_LIGHTNESS[mode].items()}


def _text(mode: Mode, hue: float, saturation: float, surfaces: list[str]) -> dict[str, str]:
    h, sat = hue / 360, saturation * 0.35
    if mode == "dark":
        text, header, dim = _from_hls(h, 0.88, sat), _from_hls(h, 0.96, sat), _from_hls(h, 0.60, sat)
    else:
        text, header, dim = _from_hls(h, 0.16, sat), _from_hls(h, 0.08, sat), _from_hls(h, 0.38, sat)
    return {
        "text": ensure_contrast(text, surfaces, AA_TEXT),
        "text_header": ensure_contrast(header, surfaces, AA_TEXT),
        "text_dim": ensure_contrast(dim, surfaces, AA_TEXT),
    }


def _on(color: str, *also: str) -> str:
    """Text for a filled ``color`` (a button): near-black or white, whichever reads better on it and ``also``."""
    fills = (color, *also)
    dark, light = "#121214", "#ffffff"
    return dark if min(contrast(dark, f) for f in fills) >= min(contrast(light, f) for f in fills) else light


def _accents(mode: Mode, accent: str, secondary: str, surfaces: list[str], border: str) -> dict[str, str]:
    accent = ensure_contrast(accent, surfaces, AA_TEXT)
    _, lightness, _ = _hls(accent)
    if mode == "dark":
        hover = _shift(accent, -0.08 if lightness > 0.9 else 0.07)
        dim = _shift(accent, -lightness * 0.4)
    else:
        hover = _shift(accent, -0.07)
        dim = _shift(accent, (1 - lightness) * 0.45)
    on_accent = _on(accent, hover)
    purple = ensure_contrast(secondary, surfaces, AA_TEXT)
    return {
        "accent": accent,
        "accent_hover": hover,
        "accent_dim": dim,
        "on_accent": on_accent,
        "purple": purple,
        "purple_hover": _shift(purple, 0.08 if mode == "dark" else -0.08),
        "border_accent": _mix(accent, border, 0.3),
    }


def _accent_color(mode: Mode, style: ClassStyle | None) -> str:
    if style is None:
        return _CLASSIC_ACCENT
    if mode == "light" and style.light_accent:
        return style.light_accent
    return style.color


def build_palette(mode: Mode = "dark", wow_class: str | None = None) -> Palette:
    """The palette for ``mode``, styled after ``wow_class`` (one of ``VANILLA_CLASSES``) or plain when None."""
    if mode not in MODES:
        raise ValueError(f"Unknown theme mode '{mode}'")
    style = CLASS_STYLES.get(wow_class) if wow_class else None
    if wow_class and style is None:
        raise ValueError(f"'{wow_class}' is not a vanilla class")

    hue, saturation = (style.tint, style.saturation) if style else _CLASSIC_TINT
    if style is None and mode == "dark":
        colors = dict(_CLASSIC_DARK)
    else:
        colors = _surfaces(mode, hue, saturation)
    surfaces = [colors[s] for s in SURFACES]

    if style is None and mode == "dark":
        for token in ("text", "text_header", "text_dim"):
            colors[token] = ensure_contrast(colors[token], surfaces, AA_TEXT)
        colors["accent"] = ensure_contrast(colors["accent"], surfaces, AA_TEXT)
        colors["purple"] = ensure_contrast(colors["purple"], surfaces, AA_TEXT)
        colors["on_accent"] = _on(colors["accent"], colors["accent_hover"])
    else:
        colors.update(_text(mode, hue, saturation, surfaces))
        accent = _accent_color(mode, style)
        secondary = style.secondary if style else _CLASSIC_DARK["purple"]
        colors.update(_accents(mode, accent, secondary, surfaces, colors["border"]))

    gold = _accent_color(mode, style) if style or mode == "light" else "#ffd100"
    colors["text_gold"] = ensure_contrast(gold, surfaces, AA_TEXT)
    colors.update(_DANGER)
    for token, value in _SEMANTIC.items():
        colors[token] = ensure_contrast(value, surfaces, AA_TEXT)

    return Palette(
        mode=mode,
        wow_class=style.name if style else None,
        colors=colors,
        class_colors={name: ensure_contrast(c, surfaces, AA_TEXT) for name, c in CLASS_COLORS.items()},
        series=tuple(ensure_contrast(c, [colors["bg_card"], colors["bg_dark"]], AA_GRAPHICS) for c in _SERIES),
    )


def class_for(player_class: str | None) -> str | None:
    """``player_class`` as one of ``VANILLA_CLASSES`` (any case), or None for anything else."""
    wanted = (player_class or "").strip().lower()
    return next((c for c in VANILLA_CLASSES if c.lower() == wanted), None)
