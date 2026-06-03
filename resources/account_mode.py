import json
from pathlib import Path


APP_SETTINGS_PATH = Path(__file__).with_name("app_settings.json")
PA_CREDENTIALS_MODE = "pa_credentials"
STEAM_BROWSER_MODE = "steam_browser"
DEFAULT_ACCOUNT_MODE = PA_CREDENTIALS_MODE
STEAM_BROWSER_PROFILE_PREPARED_KEY = "steam_browser_profile_prepared"

ACCOUNT_MODE_LABELS = {
    PA_CREDENTIALS_MODE: "Pearl Abyss Account",
    STEAM_BROWSER_MODE: "Steam Account",
}

ACCOUNT_MODE_DETAILS = {
    PA_CREDENTIALS_MODE: "Email/password refresh",
    STEAM_BROWSER_MODE: "Browser refresh",
}

ACCOUNT_MODE_ALIASES = {
    "pa": PA_CREDENTIALS_MODE,
    "pearl abyss": PA_CREDENTIALS_MODE,
    "pearl abyss account": PA_CREDENTIALS_MODE,
    "pearl abyss credentials": PA_CREDENTIALS_MODE,
    "credentials": PA_CREDENTIALS_MODE,
    "steam": STEAM_BROWSER_MODE,
    "steam account": STEAM_BROWSER_MODE,
    "steam browser": STEAM_BROWSER_MODE,
    "steam browser session": STEAM_BROWSER_MODE,
}


def normalize_account_mode(mode):
    value = str(mode or "").strip().lower()
    value = ACCOUNT_MODE_ALIASES.get(value, value)
    if value not in ACCOUNT_MODE_LABELS:
        raise ValueError(f"Unknown account mode: {mode}")
    return value


def _read_settings():
    try:
        with APP_SETTINGS_PATH.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError, TypeError):
        return {}

    return data if isinstance(data, dict) else {}


def _write_settings(data):
    APP_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with APP_SETTINGS_PATH.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")


def _coerce_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y"}
    return bool(value)


def load_account_mode():
    settings = _read_settings()
    try:
        return normalize_account_mode(settings.get("account_mode", DEFAULT_ACCOUNT_MODE))
    except ValueError:
        return DEFAULT_ACCOUNT_MODE


def save_account_mode(mode):
    normalized = normalize_account_mode(mode)
    settings = _read_settings()
    settings["account_mode"] = normalized
    _write_settings(settings)
    return normalized


def load_steam_browser_profile_prepared():
    settings = _read_settings()
    return _coerce_bool(settings.get(STEAM_BROWSER_PROFILE_PREPARED_KEY, False))


def save_steam_browser_profile_prepared(prepared=True):
    value = bool(prepared)
    settings = _read_settings()
    settings[STEAM_BROWSER_PROFILE_PREPARED_KEY] = value
    _write_settings(settings)
    return value


def account_mode_label(mode):
    return ACCOUNT_MODE_LABELS[normalize_account_mode(mode)]


def account_mode_detail(mode):
    return ACCOUNT_MODE_DETAILS[normalize_account_mode(mode)]
