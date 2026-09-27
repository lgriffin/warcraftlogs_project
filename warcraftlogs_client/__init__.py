"""WCL Analyzer desktop app and CLI, built on wcl-core."""

from pathlib import Path

from wcl_core import paths as _paths

# Keep config.json, the database and the cache in the project root, as before wcl-core was split out.
_paths.set_app_dir(Path(__file__).resolve().parent.parent)
