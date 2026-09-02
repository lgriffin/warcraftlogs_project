"""
Shared styles for the application — WoW-themed dark palette.
"""

COLORS = {
    # Backgrounds — dark charcoal/slate
    "bg_dark": "#121214",
    "bg_mid": "#1a1a1f",
    "bg_card": "#22222a",
    "bg_input": "#2a2a35",
    "bg_hover": "#32323e",
    # WoW Gold accent (primary)
    "accent": "#c9a42c",
    "accent_hover": "#dbb734",
    "accent_dim": "#8a7020",
    # Secondary accent
    "purple": "#8b5cf6",
    "purple_hover": "#a78bfa",
    # Text
    "text": "#e0e0e0",
    "text_dim": "#888892",
    "text_header": "#f5f5f5",
    "text_gold": "#ffd100",
    # Borders
    "border": "#2f2f3a",
    "border_accent": "#4a4535",
    # Semantic
    "success": "#1eff00",
    "warning": "#ff8000",
    "error": "#e74c3c",
    # WoW quality/ranking colors
    "quality_common": "#9d9d9d",
    "quality_uncommon": "#1eff00",
    "quality_rare": "#0070dd",
    "quality_epic": "#a335ee",
    "quality_legendary": "#ff8000",
}

CLASS_COLORS = {
    "Warrior": "#C79C6E",
    "Paladin": "#F58CBA",
    "Priest": "#FFFFFF",
    "Shaman": "#0070DE",
    "Druid": "#FF7D0A",
    "Rogue": "#FFF569",
    "Mage": "#69CCF0",
    "Warlock": "#9482C9",
    "Hunter": "#ABD473",
}

COMMON_STYLES = f"""
    QWidget {{
        color: {COLORS["text"]};
        font-family: "Segoe UI", sans-serif;
    }}
    QLabel {{
        color: {COLORS["text"]};
    }}
    QLineEdit {{
        background-color: {COLORS["bg_input"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 4px;
        padding: 8px 12px;
        font-size: 13px;
    }}
    QLineEdit:focus {{
        border-color: {COLORS["accent"]};
    }}
    QPushButton {{
        background-color: {COLORS["accent"]};
        color: #121214;
        border: none;
        border-radius: 4px;
        padding: 8px 20px;
        font-size: 13px;
        font-weight: bold;
    }}
    QPushButton:hover {{
        background-color: {COLORS["accent_hover"]};
    }}
    QPushButton:disabled {{
        background-color: #3a3a3a;
        color: #666;
    }}
    QPushButton[secondary="true"] {{
        background-color: {COLORS["bg_card"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
    }}
    QPushButton[secondary="true"]:hover {{
        background-color: {COLORS["bg_hover"]};
        border-color: {COLORS["accent_dim"]};
    }}
    QComboBox {{
        background-color: {COLORS["bg_input"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 4px;
        padding: 6px 10px;
        font-size: 13px;
    }}
    QComboBox:focus {{
        border-color: {COLORS["accent"]};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {COLORS["bg_input"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
        selection-background-color: {COLORS["bg_hover"]};
        selection-color: {COLORS["text_header"]};
    }}
    QCheckBox {{
        color: {COLORS["text"]};
        spacing: 8px;
        font-size: 13px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
    }}
    QProgressBar {{
        background-color: {COLORS["bg_input"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 4px;
        text-align: center;
        color: {COLORS["text"]};
        font-size: 11px;
        height: 20px;
    }}
    QProgressBar::chunk {{
        background-color: {COLORS["accent"]};
        border-radius: 3px;
    }}
    QTabWidget::pane {{
        background-color: {COLORS["bg_card"]};
        border: 1px solid {COLORS["border"]};
        border-top: none;
    }}
    QTabBar::tab {{
        background-color: {COLORS["bg_input"]};
        color: {COLORS["text_dim"]};
        padding: 12px 24px;
        border: 1px solid {COLORS["border"]};
        border-bottom: none;
        margin-right: 2px;
        font-size: 12px;
    }}
    QTabBar::tab:selected {{
        background-color: {COLORS["bg_card"]};
        color: {COLORS["text_gold"]};
        border-bottom: 2px solid {COLORS["accent"]};
    }}
    QTabBar::tab:hover:!selected {{
        background-color: {COLORS["bg_hover"]};
    }}
    QTabBar QToolButton {{
        background-color: {COLORS["bg_input"]};
        color: {COLORS["text_gold"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 3px;
        padding: 4px;
        margin: 2px;
    }}
    QTabBar QToolButton:hover {{
        background-color: {COLORS["bg_hover"]};
        color: {COLORS["accent"]};
    }}
    QTableView {{
        background-color: {COLORS["bg_card"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
        gridline-color: {COLORS["border"]};
        font-size: 12px;
        selection-background-color: {COLORS["bg_hover"]};
    }}
    QTableView::item {{
        padding: 6px 10px;
    }}
    QHeaderView::section {{
        background-color: {COLORS["bg_input"]};
        color: {COLORS["text_gold"]};
        border: 1px solid {COLORS["border"]};
        padding: 6px 8px;
        font-size: 12px;
        font-weight: bold;
    }}
    QSpinBox {{
        background-color: {COLORS["bg_input"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 4px;
        padding: 6px 10px;
        font-size: 13px;
    }}
    QSpinBox:focus {{
        border-color: {COLORS["accent"]};
    }}
    QGroupBox {{
        color: {COLORS["text_gold"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 6px;
        margin-top: 14px;
        padding-top: 18px;
        font-size: 13px;
        font-weight: bold;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
    }}
    QScrollArea {{
        border: none;
    }}
    QMessageBox {{
        background-color: {COLORS["bg_card"]};
    }}
    QMessageBox QLabel {{
        color: {COLORS["text"]};
        font-size: 13px;
        min-width: 300px;
    }}
    QMessageBox QPushButton {{
        min-width: 80px;
    }}
"""
