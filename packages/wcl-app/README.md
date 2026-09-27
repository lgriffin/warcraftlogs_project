# wcl-app

The application services of the WCL Analyzer: the use cases the CLI, the desktop app, and the Toads Hub
API and worker share. It sits on `wcl-core` (Warcraft Logs client and analysis) and `wcl-store` (storage) and
imports no Qt, no `sqlite3` and nothing from the desktop app. `warcraftlogs_client.services` is an alias of it.

- `wcl_app.context`: `AppContext` (config, WCL client, storage) and `AnalysisThresholds`
- `wcl_app.raids`: `RaidService` (analyse a report with saved role overrides, store, list, delete, import)
- `wcl_app.players`: `PlayerService` (character profile and history)
- `wcl_app.player_page`: `PlayerPageService` (a member's own page of logs)
- `wcl_app.roles`: `RoleOverrideService` (pin a character's role and re-analyse the raids it changes)
- `wcl_app.lineage`: `character_lineage` (min / mean / max across raids)

Install from another project, pinned to a commit (all three packages from the same commit):

```toml
[project]
dependencies = ["wcl-app", "wcl-store[postgres]"]

[tool.uv.sources.wcl-core]
git = "https://github.com/lgriffin/warcraftlogs_project"
subdirectory = "packages/wcl-core"
rev = "<sha>"

[tool.uv.sources.wcl-store]
git = "https://github.com/lgriffin/warcraftlogs_project"
subdirectory = "packages/wcl-store"
rev = "<sha>"

[tool.uv.sources.wcl-app]
git = "https://github.com/lgriffin/warcraftlogs_project"
subdirectory = "packages/wcl-app"
rev = "<sha>"
```

A headless host passes its own WCL client and storage, so nothing reads `config.json` or opens SQLite:

```python
from wcl_core.auth import TokenManager
from wcl_core.client import WarcraftLogsClient
from wcl_store.postgres import PostgresRaidRepository, make_engine
from wcl_app import AppContext, RaidService

engine = make_engine(database_url)
client = WarcraftLogsClient(TokenManager(client_id, client_secret))
ctx = AppContext.headless(client, storage=lambda: PostgresRaidRepository(engine))

analysis = RaidService(ctx).analyze_and_save(report_code)  # applies saved role overrides
```

`config` is optional (`AppContext.headless(client, storage, config={"role_thresholds": {...}})`). Set
`WCL_APP_DIR` as for wcl-core. Reference reports (`reference=True`) need a signed-in user token and raise
`ReferenceAuthRequired` otherwise.
