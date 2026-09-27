import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from . import paths

logger = logging.getLogger(__name__)

CACHE_DIR = str(paths.get_cache_dir())
QUERY_CACHE_DIR = str(Path(CACHE_DIR) / "responses")


def _safe_filename(report_id: str) -> str:
    return report_id.replace("/", "_")


def _cache_file(report_id: str) -> str:
    return str(Path(CACHE_DIR) / f"{_safe_filename(report_id)}.json")


def load_cached_data(report_id: str) -> dict | None:
    path = Path(_cache_file(report_id))
    if path.exists():
        try:
            with path.open(encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning("Cache file is corrupted: %s", path)
    return None


def save_cache(report_id: str, data: dict) -> None:
    path = Path(_cache_file(report_id))
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        logger.error("Failed to save cache: %s", e)


def get_cached_actor_data(cache: dict, actor_name: str, data_type: str) -> Any | None:
    return cache.get(data_type, {}).get(actor_name)


def set_cached_actor_data(cache: dict, actor_name: str, data_type: str, new_data: Any) -> None:
    if data_type not in cache:
        cache[data_type] = {}
    cache[data_type][actor_name] = new_data


def get_cached_response(query: str) -> dict | None:
    Path(QUERY_CACHE_DIR).mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(query.encode()).hexdigest()
    path = Path(QUERY_CACHE_DIR) / f"{key}.json"
    if path.exists():
        try:
            with path.open(encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return None


def save_response_cache(query: str, data: dict) -> None:
    Path(QUERY_CACHE_DIR).mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(query.encode()).hexdigest()
    path = Path(QUERY_CACHE_DIR) / f"{key}.json"
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def clear_response_cache() -> int:
    """Delete all cached API responses. Returns number of files removed."""
    count = 0
    query_dir = Path(QUERY_CACHE_DIR)
    if query_dir.is_dir():
        for fpath in query_dir.iterdir():
            try:
                fpath.unlink()
                count += 1
            except OSError:
                pass
    return count


WOWHEAD_CACHE_FILE = str(Path(CACHE_DIR) / "wowhead_names.json")


def load_wowhead_cache() -> dict:
    if Path(WOWHEAD_CACHE_FILE).exists():
        try:
            with Path(WOWHEAD_CACHE_FILE).open(encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"items": {}, "tooltips": {}}


def save_wowhead_cache(cache: dict) -> None:
    Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
    try:
        with Path(WOWHEAD_CACHE_FILE).open("w", encoding="utf-8") as f:
            json.dump(cache, f)
    except OSError:
        pass
