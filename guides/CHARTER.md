# WarcraftLogs Analyzer Engineering Charter

**Charter revision:** 1 (2026-10-03) · **Status:** adopted

The governing statement of how the analyzer and its shared packages (`wcl-core`, `wcl-store`, `wcl-app`) are
designed, tested, gated, secured, documented and released. It follows the charter of
[ESI.ts](https://github.com/lgriffin/ESI.ts): every requirement is one EARS sentence with an ID and a status, and an
Enforced requirement names the check that fails when it is broken. `tests/test_charter.py` audits this file the way
`tests/test_spec_audit.py` audits the feature files.

Product behaviour (profiles, eras, Discord identity) is specified in
[identity_and_profiles.md](identity_and_profiles.md) and `tests/features/`; this charter governs how the code is
built, not what it does.

---

## Part 0 · How to read this

This is a control document, not a tutorial. It states what the project holds itself to and points at the mechanism
that proves it. Where the mechanism does not exist yet, the requirement says so with its status.

### Requirement identifiers

| Prefix | Governs | Where the detail lives |
| --- | --- | --- |
| `ARCH` | Layers, seams, storage boundaries | `CLAUDE.md` (Architecture rules), `test_architecture` |
| `DES` | Public surface, payload contracts, errors | `tests/api_surface.txt`, the payload guides |
| `TEST` | Test tiers, specification discipline, coverage and mutation | [TESTING.md](TESTING.md) |
| `GATE` | What runs locally, in pre-commit and in CI | `scripts/dev.py`, `.github/workflows/ci.yml` |
| `SEC` | Secrets, input handling, supply chain | `tests/test_security.py`, the `security` job |
| `DOC` | Where documentation lives and how it stays true | `guides/` |
| `REL` | Packages, versions, releases | `build_release.sh`, the package jobs |
| `PROC` | How changes land | `CLAUDE.md` (Conventions) |

### Status legend

| Status | Meaning |
| --- | --- |
| **Enforced** | A test or CI job fails on violation |
| **Practised** | True in the code, but not machine-checked |
| **Partial** | Holds in some places |
| **Gap** | Stated intent, not yet true |

### Form and precedence

Each requirement is a `#### ID · Pattern · Status` block. The pattern is one of the five EARS patterns the feature
files use: Ubiquitous, Event-driven (_When_), State-driven (_While_), Optional (_Where_) and Unwanted (_If … then_).
The first paragraph is the requirement: one _shall_, the system named, no vague words. A **Verified by** bullet names
the mechanism; for an Enforced block it must name at least one that exists (a path, a test, a `dev.py` task, a CI
job, or `branch protection`), and every path it names must exist.

Precedence when documents disagree: the running code and its CI results are the fact. This charter is the intent. A
guide explains how to meet the intent. If code and charter diverge, fix one of them in the same pull request.

---

## Part 1 · Posture

1. **Reuse is the point.** The Toads Hub and its bot run `wcl-core`, `wcl-store` and `wcl-app` from this repo. Code
   goes into those packages first and every frontend adapts it, so a feature built for the desktop is already there
   for the Hub.
2. **Seams, not mocks.** HTTP goes through `wcl_core.http` and time through `wcl_core.clock`, and `wcl_core.testing`
   ships fakes for both. Tests run the real client, token managers and analysis behind those seams.
3. **The specification executes.** Behaviour is stated as EARS scenarios, one _shall_ each, bound to step
   definitions; the audit fails a pull request that breaks the form.
4. **Every gate is a ratchet.** Coverage and mutation floors only go up; `KNOWN_VIOLATIONS` and `KNOWN_STEP_MOCKS`
   only shrink; the API snapshot changes only on purpose.
5. **One verdict.** `scripts/dev.py` holds every check; CI, pre-commit and `make` call it, and `ci-success` is the
   one required check.

---

## Part 2 · Architecture

#### ARCH-01 · Ubiquitous · Enforced

Each layer of the analyzer **shall** import only modules from its own layer or an inner one, in the order core,
persistence, services, presenters, frontends.

- **Why:** the Hub and the bot reuse the inner layers; an outward import drags Qt or SQLite into a web host.
- **Verified by:** `tests/test_architecture.py::test_no_new_layer_violations` over the whole tree, and the
  `[tool.importlinter]` contracts in `pyproject.toml` run by `python scripts/dev.py imports` in the `lint` job.

#### ARCH-02 · Ubiquitous · Partial

Every frontend module **shall** reach storage, the API client and the analysis engine through a `wcl_app` service.

- **Why:** a view that reads storage itself is a feature the Hub cannot reuse.
- **Verified by:** `tests/test_architecture.py::test_known_violations_are_not_stale` holds the desktop shortcuts to
  `KNOWN_VIOLATIONS`, which fails on a new edge and on a stale entry, so the list only shrinks.

#### ARCH-03 · Ubiquitous · Enforced

The `wcl-core` and `wcl-app` packages **shall** import no `sqlite3` module.

- **Why:** SQL lives in `wcl-store`, so two backends (SQLite on the desktop, Postgres on the Hub) stay
  interchangeable behind one protocol.
- **Verified by:** the import-linter contracts in `pyproject.toml` that forbid `sqlite3` in both, checked by
  `python scripts/dev.py imports` in the `lint` job.

#### ARCH-04 · Ubiquitous · Enforced

Every storage operation a service calls **shall** be declared on `RaidRepository` and pass the same contract test on
SQLite and on Postgres.

- **Why:** a method only one backend has breaks the Hub on the first page that calls it.
- **Verified by:** `tests/test_store_contract.py`, run on both backends by the `storage-postgres` job, which fails
  on any skip.

#### ARCH-05 · Event-driven · Enforced

When the Postgres schema changes, the change **shall** land as a new numbered Alembic revision that matches
`schema.py` and downgrades cleanly.

- **Why:** the Hub's database is upgraded in place; a hand-edited schema cannot be.
- **Verified by:** `tests/test_wcl_store_package.py::test_migrations_match_the_schema_and_downgrade_cleanly` in the
  `storage-postgres` job.

#### ARCH-06 · Ubiquitous · Enforced

The shared packages **shall** send every HTTP request through `wcl_core.http` with an explicit timeout.

- **Why:** one seam lets every test answer with `FakeWarcraftLogs` or `FakeDiscord`, and a request without a
  timeout can hang a Hub worker.
- **Verified by:** `tests/test_wcl_core_testing.py::test_the_shared_packages_reach_http_only_through_the_seam`.

#### ARCH-07 · Ubiquitous · Enforced

The shared packages **shall** read the time and sleep only through `wcl_core.clock`.

- **Why:** token expiry, retry backoff and "this week" are then testable with `FakeClock`, without waiting or
  depending on the day.
- **Verified by:** `tests/test_clock.py::test_the_packages_read_the_time_only_through_wcl_core_clock`, alias-aware
  and with no allow-list.

#### ARCH-08 · Ubiquitous · Partial

The desktop application **shall** read the time only through `wcl_core.clock`.

- **Why:** the updater's cooldown and the GUI's timestamps are the last direct clock reads.
- **Verified by:** none yet; `tests/test_clock.py` covers `packages/` only.

---

## Part 3 · Design

#### DES-01 · Ubiquitous · Enforced

Every public name of `wcl_app`, `wcl_store`, `wcl_core.clock`, `wcl_core.http` and `wcl_core.testing` **shall** be
recorded with its signature in `tests/api_surface.txt`.

- **Why:** the Hub builds on these names; a change to one must be a decision visible in review, not a side effect.
- **Verified by:** `tests/test_api_contract.py::test_the_public_surface_matches_the_snapshot`, which lists removed
  lines as breaking; `WCL_UPDATE_SURFACE=1` regenerates the file.

#### DES-02 · Ubiquitous · Practised

Each payload the Hub shares with the desktop **shall** have a guide that states its fields.

- **Why:** the Home widgets, badges and reference comparison are rendered by two frontends from one payload.
- **Verified by:** `guides/home_widgets.md`, `guides/badges.md`, `guides/reference_comparison.md` and
  `guides/charts.md`; nothing compares a guide's fields with its payload.

#### DES-03 · Ubiquitous · Partial

Every error a service raises **shall** be a subclass of `WarcraftLogsError` or `StorageError`.

- **Why:** frontends branch on errors; a bare `ValueError` from a service reaches the user as a crash.
- **Verified by:** `wcl_core.common.errors` and `wcl_store.StorageError` exist; no test holds every service to them.

#### DES-04 · Ubiquitous · Gap

The analyzer **shall** parse every Warcraft Logs response it reads with a model that accepts unknown fields.

- **Why:** Warcraft Logs adds fields on its own schedule; GraphQL replies are parsed by hand today.
- **Verified by:** none yet.

---

## Part 4 · Testing

#### TEST-01 · Ubiquitous · Enforced

Every scenario in `tests/features/` **shall** state one EARS requirement under one pattern tag.

- **Why:** the feature files are the specification; a scenario with two obligations proves neither cleanly.
- **Verified by:** `tests/test_spec_audit.py::test_every_scenario_is_one_ears_requirement` and
  `tests/test_spec_audit.py::test_every_feature_file_is_bound_to_step_definitions`.

#### TEST-02 · Ubiquitous · Partial

Every step definition **shall** replace only the HTTP seam, through `wcl_core.testing`, never `unittest.mock`.

- **Why:** a mocked service proves the mock; a fake transport proves the client, the token manager and the service.
- **Verified by:** `tests/test_suite_health.py::test_step_definitions_mock_only_at_the_http_seam`, which holds the
  four remaining step modules to `KNOWN_STEP_MOCKS` and fails on a new one.

#### TEST-03 · Ubiquitous · Enforced

Every test **shall** carry its proof: an assertion when it runs, a reason when it is skipped.

- **Why:** a test with no assertion and a skip with no reason both pass while proving nothing.
- **Verified by:** `tests/test_suite_health.py::test_every_test_checks_something`,
  `tests/test_suite_health.py::test_every_skip_and_xfail_says_why` and
  `tests/test_suite_health.py::test_no_test_swallows_every_exception`.

#### TEST-04 · Ubiquitous · Enforced

Every public name of the shared packages and every public method of an exported service **shall** be used by a test.

- **Why:** an export no test touches can break without a red build.
- **Verified by:** `tests/test_api_contract.py::test_every_export_is_used_by_a_test` and
  `tests/test_api_contract.py::test_every_service_and_repository_method_is_used_by_a_test`.

#### TEST-05 · Ubiquitous · Enforced

Each mutation target in `[tool.wcl.mutation]` **shall** kill at least its floor's share of the mutants
`scripts/mutate.py` plants.

- **Why:** coverage shows a line ran; mutation shows a test would notice it change.
- **Verified by:** `scripts/mutate.py`, run by `python scripts/dev.py mutation` in the `mutation` job; floors only
  go up.

#### TEST-06 · Unwanted · Enforced

If line coverage falls below `fail_under` in `pyproject.toml`, then the test run **shall** fail.

- **Why:** the floor stops coverage eroding one pull request at a time; it is raised, never lowered.
- **Verified by:** `python scripts/dev.py test` in the `test` job, and `python scripts/dev.py diffcov` for the lines
  each pull request changes.

#### TEST-07 · Ubiquitous · Enforced

The property-based suite in `tests/fuzz/` **shall** run on every pull request.

- **Why:** analysis code takes arbitrary report data; properties find inputs nobody wrote down.
- **Verified by:** `python scripts/dev.py fuzz` in the `fuzz` job.

#### TEST-08 · Ubiquitous · Enforced

The PySide6 widget tests **shall** run headless on every pull request.

- **Why:** the desktop is a frontend like any other and breaks the same way.
- **Verified by:** `python scripts/dev.py gui` in the `gui-test` job.

#### TEST-09 · Ubiquitous · Partial

Every fuzz property **shall** fail against a registered known-bad implementation.

- **Why:** a property that cannot fail is decoration.
- **Verified by:** none yet; `tests/fuzz/` has the properties but not the bad implementations.

---

## Part 5 · Gates

#### GATE-01 · Ubiquitous · Enforced

The `master` branch **shall** accept only pull requests whose `ci-success` check passed.

- **Why:** one required check that needs every job means a dropped or skipped job cannot pass silently.
- **Verified by:** `branch protection` (a ruleset on `master`), the `ci-success` job, `scripts/ci_gate.py`, and
  `tests/test_dev_tasks.py::test_the_gate_waits_on_every_job`.

#### GATE-02 · Ubiquitous · Enforced

Each CI job **shall** run exactly the `scripts/dev.py` tasks listed for it in `tests/test_dev_tasks.py`.

- **Why:** `python scripts/dev.py check` gives the same verdict locally as CI only while the two agree.
- **Verified by:** `tests/test_dev_tasks.py::test_each_job_runs_its_dev_tasks` and
  `tests/test_dev_tasks.py::test_only_the_gate_has_a_job_level_if`.

#### GATE-03 · Ubiquitous · Enforced

Every function the shared packages and the desktop core add **shall** stay at or under a cyclomatic complexity of 15.

- **Why:** the existing `# noqa: C901` functions are a list to shrink, not a pattern to copy.
- **Verified by:** `max-complexity = 15` in `pyproject.toml`, checked by `python scripts/dev.py lint` in the `lint`
  job.

#### GATE-04 · Ubiquitous · Practised

Every checker version **shall** be pinned in the `dev` extra and raised through Dependabot.

- **Why:** a new release of a checker can add rules; an unpinned one turns `master` red without a change.
- **Verified by:** `pyproject.toml` and `.github/dependabot.yml`; nothing fails when a pin is loosened.

#### GATE-05 · Ubiquitous · Practised

The pre-commit hooks **shall** run the same `scripts/dev.py` tasks as CI.

- **Why:** a commit that passes locally and fails in CI wastes a cycle.
- **Verified by:** `.pre-commit-config.yaml`; `tests/test_dev_tasks.py::test_every_caller_names_a_real_task` checks
  it names real tasks, not that it names all of them.

---

## Part 6 · Security

#### SEC-01 · Unwanted · Enforced

If a commit carries a credential, then the `gitleaks` job **shall** fail.

- **Why:** `config.json` holds API credentials and is git-ignored; the scan catches one pasted anywhere else.
- **Verified by:** the `gitleaks` job over the whole history, and `.gitignore`.

#### SEC-02 · Unwanted · Enforced

If a log line or an authentication error would carry a client secret or token, then the analyzer **shall** write it
masked.

- **Why:** logs and error reports are shared with officers; a token in one is a leaked account.
- **Verified by:** `tests/test_secret_logging.py` and
  `tests/test_security.py::test_secret_not_in_error_messages`, which supply the secret and look for it.

#### SEC-03 · Ubiquitous · Enforced

The analyzer **shall** send report codes and character names to Warcraft Logs as GraphQL variables.

- **Why:** a name pasted into a query string is an injection.
- **Verified by:** `tests/test_security.py`, whose tests check the query text carries neither value.

#### SEC-04 · Ubiquitous · Enforced

The shared packages and the desktop core **shall** pass `bandit` and `pip-audit` on every pull request.

- **Why:** static security rules and known-vulnerable dependencies are cheap to catch and expensive to ship.
- **Verified by:** `python scripts/dev.py security` and `python scripts/dev.py audit` in the `security` job.

#### SEC-05 · Ubiquitous · Enforced

The desktop Discord sign-in **shall** use PKCE with the `identify` scope and no client secret.

- **Why:** a desktop app cannot keep a secret; PKCE makes an intercepted code useless.
- **Verified by:** `tests/test_discord_auth.py`.

---

## Part 7 · Documentation

#### DOC-01 · Ubiquitous · Enforced

This charter **shall** hold every requirement block to the EARS form and every Enforced block to a mechanism that
exists.

- **Why:** a charter that drifts from the code is worse than none.
- **Verified by:** `tests/test_charter.py`.

#### DOC-02 · Ubiquitous · Gap

Every guide in `guides/` **shall** open with the charter requirements it implements.

- **Why:** a reader of a guide should find the rule it serves, and a changed rule should find its guides.
- **Verified by:** none yet; ESI.ts does this with an `Implements:` line.

---

## Part 8 · Release

#### REL-01 · Ubiquitous · Enforced

Each of the `wcl-core`, `wcl-store` and `wcl-app` wheels **shall** build and import alone in a fresh environment.

- **Why:** the Hub installs the wheels, not this repo; a hidden import of the desktop app only shows there.
- **Verified by:** the `wcl-core-package`, `wcl-store-package` and `wcl-app-package` jobs.

#### REL-02 · Ubiquitous · Gap

Every release **shall** take its version and changelog from conventional commit messages.

- **Why:** `build_release.sh` bumps versions by hand, and the Hub pins those versions.
- **Verified by:** none yet.

---

## Part 9 · Process

#### PROC-01 · Ubiquitous · Enforced

Every change to `master` **shall** land through a pull request.

- **Why:** review and `ci-success` see every change.
- **Verified by:** `branch protection` (the same ruleset as GATE-01).

#### PROC-02 · Ubiquitous · Practised

Each pull request **shall** carry one concern and update the guides it affects.

- **Why:** a reviewer can hold one change in mind; a guide fixed later is a guide that stays wrong.
- **Verified by:** review.

---

## Part 10 · Gap register

The Partial, Practised and Gap rows worth closing, cheapest first: ARCH-08 (move `updater.py` onto the clock),
TEST-02 (empty `KNOWN_STEP_MOCKS`), DOC-02 (an `Implements:` line per guide), DES-03 (a test over service errors),
DES-02 (a test that each payload guide names its fields), TEST-09 (bad implementations for the fuzz properties),
ARCH-02 (empty `KNOWN_VIOLATIONS`), DES-04 (response models), REL-02 (release automation). Each lands as its own pull
request and moves its row's status in the same change.
