import hashlib
import os
import json
from typing import Any, Optional

from . import paths

CACHE_DIR = str(paths.get_cache_dir())
QUERY_CACHE_DIR = os.path.join(CACHE_DIR, "responses")


def _safe_filename(report_id: str) -> str:
    return report_id.replace("/", "_")


def _cache_file(report_id: str) -> str:
    return os.path.join(CACHE_DIR, f"{_safe_filename(report_id)}.json")


def load_cached_data(report_id: str) -> Optional[dict]:
    path = _cache_file(report_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Cache file is corrupted: {path}")
    return None


def save_cache(report_id: str, data: dict) -> None:
    path = _cache_file(report_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        print(f"Failed to save cache: {e}")


def get_cached_actor_data(cache: dict, actor_name: str, data_type: str) -> Optional[Any]:
    return cache.get(data_type, {}).get(actor_name)


def set_cached_actor_data(cache: dict, actor_name: str, data_type: str, new_data: Any) -> None:
    if data_type not in cache:
        cache[data_type] = {}
    cache[data_type][actor_name] = new_data


def get_cached_response(query: str) -> Optional[dict]:
    os.makedirs(QUERY_CACHE_DIR, exist_ok=True)
    key = hashlib.sha256(query.encode()).hexdigest()
    path = os.path.join(QUERY_CACHE_DIR, f"{key}.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return None


def save_response_cache(query: str, data: dict) -> None:
    os.makedirs(QUERY_CACHE_DIR, exist_ok=True)
    key = hashlib.sha256(query.encode()).hexdigest()
    path = os.path.join(QUERY_CACHE_DIR, f"{key}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


WOWHEAD_CACHE_FILE = os.path.join(CACHE_DIR, "wowhead_names.json")


def load_wowhead_cache() -> dict:
    if os.path.exists(WOWHEAD_CACHE_FILE):
        try:
            with open(WOWHEAD_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"items": {}, "enchants": {}, "tooltips": {}}


def save_wowhead_cache(cache: dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    try:
        with open(WOWHEAD_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except OSError:
        pass
