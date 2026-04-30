"""
Shared styles for the application.
"""

COLORS = {
    "bg_dark": "#0f3460",
    "bg_card": "#16213e",
    "bg_input": "#1a1a2e",
    "accent": "#e94560",
    "accent_hover": "#ff6b81",
    "text": "#eee",
    "text_dim": "#aaa",
    "text_header": "#fff",
    "border": "#2a2a4a",
    "success": "#2ecc71",
    "warning": "#f39c12",
    "error": "#e74c3c",
}

COMMON_STYLES = f"""
    QWidget {{
        color: {COLORS['text']};
        font-family: "Segoe UI", sans-serif;
    }}
    QLabel {{
        color: {COLORS['text']};
    }}
    QLineEdit {{
        background-color: {COLORS['bg_input']};
        color: {COLORS['text']};
        border: 1px solid {COLORS['border']};
        border-radius: 4px;
        padding: 8px 12px;
        font-size: 13px;
    }}
    QLineEdit:focus {{
        border-color: {COLORS['accent']};
    }}
    QPushButton {{
        background-color: {COLORS['accent']};
        color: white;
        border: none;
        border-radius: 4px;
        padding: 8px 20px;
        font-size: 13px;
        font-weight: bold;
    }}
    QPushButton:hover {{
        background-color: {COLORS['accent_hover']};
    }}
    QPushButton:disabled {{
        background-color: #555;
        color: #888;
    }}
    QPushButton[secondary="true"] {{
        background-color: {COLORS['bg_card']};
        border: 1px solid {COLORS['border']};
    }}
    QPushButton[secondary="true"]:hover {{
        background-color: {COLORS['border']};
    }}
    QComboBox {{
        background-color: {COLORS['bg_input']};
        color: {COLORS['text']};
        border: 1px solid {COLORS['border']};
        border-radius: 4px;
        padding: 6px 10px;
        font-size: 13px;
    }}
    QComboBox:focus {{
        border-color: {COLORS['accent']};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {COLORS['bg_input']};
        color: {COLORS['text']};
        border: 1px solid {COLORS['border']};
        selection-background-color: {COLORS['bg_dark']};
        selection-color: {COLORS['text_header']};
    }}
    QCheckBox {{
        color: {COLORS['text']};
        spacing: 8px;
        font-size: 13px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
    }}
    QProgressBar {{
        background-color: {COLORS['bg_input']};
        border: 1px solid {COLORS['border']};
        border-radius: 4px;
        text-align: center;
        color: {COLORS['text']};
        font-size: 11px;
        height: 20px;
    }}
    QProgressBar::chunk {{
        background-color: {COLORS['accent']};
        border-radius: 3px;
    }}
    QTabWidget::pane {{
        background-color: {COLORS['bg_card']};
        border: 1px solid {COLORS['border']};
        border-top: none;
    }}
    QTabBar::tab {{
        background-color: {COLORS['bg_input']};
        color: {COLORS['text_dim']};
        padding: 10px 20px;
        border: 1px solid {COLORS['border']};
        border-bottom: none;
        margin-right: 2px;
        font-size: 12px;
    }}
    QTabBar::tab:selected {{
        background-color: {COLORS['bg_card']};
        color: {COLORS['text_header']};
        border-bottom: 2px solid {COLORS['accent']};
    }}
    QTabBar::tab:hover:!selected {{
        background-color: {COLORS['bg_dark']};
    }}
    QTableView {{
        background-color: {COLORS['bg_card']};
        color: {COLORS['text']};
        border: 1px solid {COLORS['border']};
        gridline-color: {COLORS['border']};
        font-size: 12px;
        selection-background-color: {COLORS['bg_dark']};
    }}
    QTableView::item {{
        padding: 4px 8px;
    }}
    QHeaderView::section {{
        background-color: {COLORS['bg_input']};
        color: {COLORS['text_header']};
        border: 1px solid {COLORS['border']};
        padding: 6px 8px;
        font-size: 12px;
        font-weight: bold;
    }}
    QSpinBox {{
        background-color: {COLORS['bg_input']};
        color: {COLORS['text']};
        border: 1px solid {COLORS['border']};
        border-radius: 4px;
        padding: 6px 10px;
        font-size: 13px;
    }}
    QSpinBox:focus {{
        border-color: {COLORS['accent']};
    }}
    QGroupBox {{
        color: {COLORS['text_header']};
        border: 1px solid {COLORS['border']};
        border-radius: 6px;
        margin-top: 12px;
        padding-top: 16px;
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
        background-color: {COLORS['bg_card']};
    }}
    QMessageBox QLabel {{
        color: {COLORS['text']};
        font-size: 13px;
        min-width: 300px;
    }}
    QMessageBox QPushButton {{
        min-width: 80px;
    }}
"""
