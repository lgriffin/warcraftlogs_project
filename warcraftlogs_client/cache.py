import os
import json

CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
os.makedirs(CACHE_DIR, exist_ok=True)

def _safe_filename(report_id):
    return report_id.replace("/", "_")

def _cache_file(report_id):
    return os.path.join(CACHE_DIR, f"{_safe_filename(report_id)}.json")

def load_cached_data(report_id):
    path = _cache_file(report_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"⚠️ Cache file is corrupted: {path}")
    return None

def save_cache(report_id, data):
    path = _cache_file(report_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"💾 Saved cache for report {report_id}")
    except Exception as e:
        print(f"❌ Failed to save cache: {e}")

def get_cached_actor_data(cache, actor_name, data_type):
    return cache.get(data_type, {}).get(actor_name)

def set_cached_actor_data(cache, actor_name, data_type, new_data):
    if data_type not in cache:
        cache[data_type] = {}
    cache[data_type][actor_name] = new_data
