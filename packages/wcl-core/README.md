# wcl-core

The Warcraft Logs API client, raid analysis (`analyze_raid`) and result models used by the WCL Analyzer
desktop app and CLI, and by the Toads Hub worker. It imports no Qt and no SQLite; storage lives in
`wcl-store` and the application services in `wcl-app`.

Install from another project, pinned to a commit:

```toml
[tool.uv.sources]
wcl-core = { git = "https://github.com/lgriffin/warcraftlogs_project", subdirectory = "packages/wcl-core", rev = "<sha>" }
```

Hosts other than the desktop app should set `WCL_APP_DIR` (or call `wcl_core.paths.set_app_dir`) to choose
where `config.json` and the API cache live. Spell data and role configs ship inside the package under
`wcl_core/data/`.
