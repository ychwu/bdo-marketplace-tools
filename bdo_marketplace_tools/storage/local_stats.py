import json
from datetime import datetime

from bdo_marketplace_tools.storage.paths import LOCAL_STATS_PATH


DEFAULT_LOCAL_STATS = {
    "successful_purchases": 0,
    "silver_spent": 0,
}


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _read_json(path):
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        return {}

    return data if isinstance(data, dict) else {}


def _normalize_stats(data):
    return {
        "successful_purchases": _safe_int(data.get("successful_purchases")),
        "silver_spent": _safe_int(data.get("silver_spent")),
    }


def load_local_stats(path=LOCAL_STATS_PATH):
    if path.exists():
        return _normalize_stats(_read_json(path))

    save_local_stats(DEFAULT_LOCAL_STATS, include_timestamp=False, path=path)
    return DEFAULT_LOCAL_STATS.copy()


def save_local_stats(data, *, include_timestamp=True, path=LOCAL_STATS_PATH):
    payload = DEFAULT_LOCAL_STATS.copy()
    payload.update(_normalize_stats(data))
    if include_timestamp:
        payload["updated_at"] = datetime.now().isoformat(timespec="seconds")

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as data_file:
        json.dump(payload, data_file, indent=2)
        data_file.write("\n")
    return payload
