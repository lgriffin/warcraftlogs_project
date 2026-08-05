# WarcraftLogs Analyzer — Improvement Backlog

Audit date: 2026-08-05  
Source: architecture & best-practices review (v4.3.x)

**Principle:** One pipeline, many presenters. `analysis.analyze_raid` produces `RaidAnalysis` once; CLI, GUI, markdown, and DB are consumers — never alternate analyzers with different role rules.

---

## Status legend

| Status | Meaning |
|--------|---------|
| Done | Landed or already true in current code |
| In progress | Active PR / branch |
| Next | Highest-priority remaining work |
| Later | Valuable but after structural cleanup |
| Stale | Previously listed; superseded or incorrect |

---

## Phase roadmap

| Phase | Focus | Status |
|-------|--------|--------|
| **0** | Secrets hygiene + wire `wcl_api_url` into the API client | Done (PR) |
| **1** | Collapse dual analysis stacks; shared role classifier | Next |
| **2** | Split `database.py`; numbered migrations | Later |
| **3** | Thin GUI views; extract pure helpers; GraphQL variables | Later |
| **4** | Enforce mypy + GUI CI; honest coverage docs | Later |

---

## Phase 0 — Secrets & API host (in progress)

- [x] Stop tracking `config.json` in git (`git rm --cached`); keep `config.example.json` only
- [x] Add `user_token.json` to `.gitignore`
- [x] Accept `api_url` on `WarcraftLogsClient` and pass `config["wcl_api_url"]` from CLI/GUI/workers
- [ ] **Manual:** Rotate WCL client ID/secret at [Warcraft Logs API clients](https://www.warcraftlogs.com/api/clients/) — credentials were previously committed and remain in git history
- [ ] **Optional:** Purge secrets from git history (`git filter-repo` / BFG) if the repo is or was public

---

## Phase 1 — One analysis stack (next)

- Make CLI `healer` / `tank` / `melee` / `ranged` thin filters over `analyze_raid` + renderers (or remove the subcommands)
- Delete or quarantine: `*_main.py`, `dump_report.py`, `loader.py`, `markdown_exporter.py`
- Extract a single role-classification module used by `analysis.py` and `consumes_analysis.py` (today consumes hardcodes healer threshold `900000` and uses legacy `dynamic_role_parser`)
- Update `DEVELOPER.md` mermaid: there is no live `roles/` package; modern classification lives in `analysis.py`

---

## Phase 2 — Database modularization

- Split `database.py` (~3,100 LOC) into concern-based modules, e.g.:
  - `db/schema.py` + `db/migrations/` — DDL and sequential versioned migrations
  - `db/import_raid.py` — import helpers
  - `db/queries_trends.py` / `queries_insights.py` — read paths
  - `db/raid_groups.py` — groups CRUD
  - `db/facade.py` — thin `PerformanceDB` for callers
- Replace PRAGMA column-probing migrations with numbered scripts driven by `schema_version`
- Add indexes where trend queries need them (e.g. consumable name, healer spell name)
- Note: `PRAGMA busy_timeout=5000` and WAL/foreign keys **already exist** — do not re-add

---

## Phase 3 — GUI structure & API robustness

- Split oversized views (`charts.py`, `reference_view.py`, `character_view.py`, …); keep Qt in views, move aggregation/formatting to non-Qt helpers testable without xvfb
- Extract shared `AnalysisSession` / client factory (TokenManager + thresholds + `api_url`) used by CLI and GUI workers
- Prefer GraphQL **variables** over f-string interpolation of report/actor IDs; extend `tests/test_security.py` accordingly
- Wire `common.errors` (`ApiError`, `DataProcessingError`) into workers; replace broad `except Exception` with typed catches + retry UX
- Cache: consider TTL or schema-version keys so response cache does not outlive query-shape changes

---

## Phase 4 — Quality gates

- Align `guides/TESTING.md` (claims ~80%) with `fail_under = 55` and `omit = gui/*` in `pyproject.toml`
- Promote mypy (core package) and GUI tests off `continue-on-error` once baselines are green
- Keep vulture/radon advisory until legacy deletion (Phase 1) lands
- Raise coverage on extracted pure modules; keep GUI coverage optional until helpers are non-Qt

---

## Programmatic improvements (active)

### Error handling

- Replace remaining bare `except Exception` with specific types; use `common.errors` in production paths (workers, analysis warnings)

### Typing

- Add hints to `cache.py`, `character_api.py`, CLI, and GUI private methods; tighten mypy over time

### Database / import duplication

- `_import_healer` / `_import_tank` / `_import_dps` share structure — genericize during Phase 2 split

### Installer / packaging

- Trim unused Qt modules from the PyInstaller spec (Bluetooth, Sensors, 3D, WebEngine, Multimedia, …)
- Code signing for Windows releases; publish SHA256 checksums on GitHub Releases

---

## Functionality improvements (product)

### UX

- Granular progress is partly done (analysis progress callbacks); extend stage-level messaging where gaps remain
- Retry buttons + credential-specific error guidance on failure dialogs
- Markdown export: confirm path / offer to open
- Empty-state placeholders for blank charts

### Accessibility

- Keyboard shortcuts for analyse, export, tab switch
- Tab order in forms; contrast / high-contrast mode review

### Data & visualisation

- Multi-raid character overlay comparison
- Consumable usage timeline
- Distribution histograms with percentiles
- Chart drill-down → raid detail

### Raid groups & roster

- Composition filtering; anomaly flags (>2σ vs personal average)
- Guild roster sync from WCL; batch profile refresh

### Settings

- Config export/import (non-secret settings); optional audit trail for threshold changes

---

## Quick wins

| Improvement | Effort | Impact | Notes |
|-------------|--------|--------|-------|
| Rotate API credentials (manual) | 15 min | Critical | Required after Phase 0; secrets were in git history |
| Shared client factory with `api_url` | 1–2 h | Consistency | Builds on Phase 0 |
| Deprecate CLI `*_main` subcommands | 2–4 h | Correctness | Phase 1 start |
| Empty-state chart messages | 1 h | UX | |
| Trim unused Qt from PyInstaller | 1 h | Installer size | |
| Typed exceptions in workers | 2 h | Debuggability | |
| pytest-qt for worker signals | 4 h | Regression safety | Soft-fail GUI CI today |

---

## Corrected / stale items (from Apr 2026 backlog)

| Old claim | Reality |
|-----------|---------|
| “No API rate limiting” | **Done** — `WarcraftLogsClient` throttles (250 ms) and retries 429/5xx |
| “No `PRAGMA busy_timeout`” | **Done** — set to 5000 with WAL + foreign keys |
| “GUI has zero coverage / add pytest-qt” | Partially outdated — `tests/gui/` exists; CI still `continue-on-error` |
| Coverage “29% / target 80%” | Docs/config drift — enforce 55% on non-GUI; update TESTING.md |

---

## Review focus (recurring)

1. Never commit `config.json` or `user_token.json`
2. Prefer extending `analysis.py` + `models.py` + `client.py` over new parallel analyzers
3. Keep `PerformanceDB` callers stable via a facade when splitting the DB module
