# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for WarcraftLogs Analyzer GUI."""

from PyInstaller.utils.hooks import collect_data_files

pyside6_datas = collect_data_files("PySide6")

a = Analysis(
    ["warcraftlogs_client/gui/app.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("spell_data", "spell_data"),
        ("warcraftlogs_client/templates", "warcraftlogs_client/templates"),
        ("logo.png", "."),
        ("consumes_config.json", "."),
        ("config.example.json", "."),
    ]
    + pyside6_datas,
    hiddenimports=[
        "warcraftlogs_client.gui",
        "warcraftlogs_client.gui.app",
        "warcraftlogs_client.gui.main_window",
        "warcraftlogs_client.gui.analyze_view",
        "warcraftlogs_client.gui.history_view",
        "warcraftlogs_client.gui.raid_group_view",
        "warcraftlogs_client.gui.character_view",
        "warcraftlogs_client.gui.settings_view",
        "warcraftlogs_client.gui.charts",
        "warcraftlogs_client.gui.detail_panel",
        "warcraftlogs_client.gui.table_models",
        "warcraftlogs_client.gui.worker",
        "warcraftlogs_client.gui.styles",
        "warcraftlogs_client.paths",
        "warcraftlogs_client.analysis",
        "warcraftlogs_client.auth",
        "warcraftlogs_client.client",
        "warcraftlogs_client.config",
        "warcraftlogs_client.database",
        "warcraftlogs_client.spell_manager",
        "warcraftlogs_client.consumes_analysis",
        "warcraftlogs_client.cache",
        "warcraftlogs_client.character_api",
        "warcraftlogs_client.dynamic_role_parser",
        "warcraftlogs_client.models",
        "warcraftlogs_client.loader",
        "warcraftlogs_client.markdown_exporter",
        "warcraftlogs_client.renderers.markdown",
        "warcraftlogs_client.renderers.console",
        "warcraftlogs_client.common.data",
        "warcraftlogs_client.common.errors",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "scipy", "PIL"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WarcraftLogsAnalyzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="logo.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="WarcraftLogsAnalyzer",
)
