import json

from bdo_marketplace_tools.storage.paths import APP_SETTINGS_PATH
from bdo_marketplace_tools.version import APP_CHANNEL, APP_VERSION, PROJECT_NAME, SETTINGS_SCHEMA_VERSION


PA_CREDENTIALS_MODE = "pa_credentials"
STEAM_BROWSER_MODE = "steam_browser"
DEFAULT_ACCOUNT_MODE = PA_CREDENTIALS_MODE
STEAM_BROWSER_PROFILE_PREPARED_KEY = "steam_browser_profile_prepared"
STEAM_PA_COOKIE_CONSENT_PREPARED_KEY = "steam_pa_cookie_consent_prepared"
PA_BROWSER_PROFILE_PREPARED_KEY = "pa_browser_profile_prepared"
SETTINGS_VERSION = SETTINGS_SCHEMA_VERSION
DEFAULT_POLLING_DELAY_KEY = "3"
DEFAULT_CUSTOM_POLLING_RANGE = [15, 30]
DEFAULT_PURCHASE_DELAY_RANGE = [1.0, 2.5]
VALID_POLLING_DELAY_KEYS = {"1", "2", "3", "custom"}
DEFAULT_EVENT_LOG_VIEW = "core"
VALID_EVENT_LOG_VIEWS = {"core", "ui"}

ACCOUNT_MODE_LABELS = {
    PA_CREDENTIALS_MODE: "Pearl Abyss Account",
    STEAM_BROWSER_MODE: "Steam Account",
}

ACCOUNT_MODE_DETAILS = {
    PA_CREDENTIALS_MODE: "Browser login",
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


def default_app_settings():
    return {
        "version": _current_version_info(),
        "account": {
            "mode": DEFAULT_ACCOUNT_MODE,
            "email": None,
        },
        "steam_browser": {
            "profile_prepared": False,
            "pa_cookie_consent_prepared": False,
        },
        "pa_browser": {
            "profile_prepared": False,
        },
        "session": {
            "saved_session_last_known_valid": False,
        },
        "ui": {
            "polling": {
                "selected": DEFAULT_POLLING_DELAY_KEY,
                "custom_range": DEFAULT_CUSTOM_POLLING_RANGE[:],
            },
            "buy_delay": {
                "range": DEFAULT_PURCHASE_DELAY_RANGE[:],
            },
            "spend_cap": None,
            "buy_mode": False,
            "event_log_view": DEFAULT_EVENT_LOG_VIEW,
        },
    }


def _current_version_info():
    return {
        "schema": SETTINGS_VERSION,
        "app": APP_VERSION,
        "channel": APP_CHANNEL,
        "project": PROJECT_NAME,
    }


def _read_json(path):
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
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


def _coerce_int_range(value, default_range):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return default_range[:]
    try:
        low = int(value[0])
        high = int(value[1])
    except (TypeError, ValueError):
        return default_range[:]
    if low <= 0 or high <= 0 or low > high:
        return default_range[:]
    return [low, high]


def _coerce_float_range(value, default_range):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return default_range[:]
    try:
        low = float(value[0])
        high = float(value[1])
    except (TypeError, ValueError):
        return default_range[:]
    if low < 0 or high < 0 or low > high:
        return default_range[:]
    return [low, high]


def _coerce_spend_cap(value):
    if value in (None, "", 0, "0"):
        return None
    try:
        cap = int(value)
    except (TypeError, ValueError):
        return None
    return cap if cap > 0 else None


def _normalize_event_log_view(value):
    normalized = str(value or DEFAULT_EVENT_LOG_VIEW).strip().lower()
    return normalized if normalized in VALID_EVENT_LOG_VIEWS else DEFAULT_EVENT_LOG_VIEW


def _normalize_settings(data):
    settings = default_app_settings()
    account = data.get("account") if isinstance(data.get("account"), dict) else {}
    steam_browser = data.get("steam_browser") if isinstance(data.get("steam_browser"), dict) else {}
    pa_browser = data.get("pa_browser") if isinstance(data.get("pa_browser"), dict) else {}
    session = data.get("session") if isinstance(data.get("session"), dict) else {}
    ui = data.get("ui") if isinstance(data.get("ui"), dict) else {}
    polling = ui.get("polling") if isinstance(ui.get("polling"), dict) else {}
    buy_delay = ui.get("buy_delay") if isinstance(ui.get("buy_delay"), dict) else {}

    raw_mode = account.get("mode", data.get("account_mode", DEFAULT_ACCOUNT_MODE))
    try:
        settings["account"]["mode"] = normalize_account_mode(raw_mode)
    except ValueError:
        settings["account"]["mode"] = DEFAULT_ACCOUNT_MODE

    email = account.get("email", data.get("email"))
    settings["account"]["email"] = str(email).strip() if email else None

    prepared = steam_browser.get("profile_prepared", data.get(STEAM_BROWSER_PROFILE_PREPARED_KEY, False))
    settings["steam_browser"]["profile_prepared"] = _coerce_bool(prepared)
    steam_pa_consent_prepared = steam_browser.get(
        "pa_cookie_consent_prepared",
        data.get(STEAM_PA_COOKIE_CONSENT_PREPARED_KEY, False),
    )
    settings["steam_browser"]["pa_cookie_consent_prepared"] = _coerce_bool(steam_pa_consent_prepared)
    pa_prepared = pa_browser.get("profile_prepared", data.get(PA_BROWSER_PROFILE_PREPARED_KEY, False))
    settings["pa_browser"]["profile_prepared"] = _coerce_bool(pa_prepared)

    settings["session"]["saved_session_last_known_valid"] = _coerce_bool(
        session.get("saved_session_last_known_valid", data.get("saved_session_last_known_valid", False))
    )

    selected_delay = str(polling.get("selected", data.get("delay", DEFAULT_POLLING_DELAY_KEY))).strip().lower()
    if selected_delay not in VALID_POLLING_DELAY_KEYS:
        selected_delay = DEFAULT_POLLING_DELAY_KEY
    settings["ui"]["polling"]["selected"] = selected_delay
    settings["ui"]["polling"]["custom_range"] = _coerce_int_range(
        polling.get("custom_range", data.get("custom_delay_range", DEFAULT_CUSTOM_POLLING_RANGE)),
        DEFAULT_CUSTOM_POLLING_RANGE,
    )

    settings["ui"]["buy_delay"]["range"] = _coerce_float_range(
        buy_delay.get("range", data.get("purchase_delay_bounds", DEFAULT_PURCHASE_DELAY_RANGE)),
        DEFAULT_PURCHASE_DELAY_RANGE,
    )
    settings["ui"]["spend_cap"] = _coerce_spend_cap(ui.get("spend_cap", data.get("max_spend")))
    settings["ui"]["buy_mode"] = _coerce_bool(ui.get("buy_mode", data.get("purchase_submission_enabled", False)))
    settings["ui"]["event_log_view"] = _normalize_event_log_view(
        ui.get("event_log_view", data.get("event_log_view", DEFAULT_EVENT_LOG_VIEW))
    )
    return settings


def read_app_settings():
    if APP_SETTINGS_PATH.exists():
        raw_settings = _read_json(APP_SETTINGS_PATH)
        settings = _normalize_settings(raw_settings)
        if settings != raw_settings:
            _write_settings(settings)
        return settings

    settings = default_app_settings()
    _write_settings(settings)
    return settings


def save_app_settings(settings):
    normalized = _normalize_settings(settings)
    _write_settings(normalized)
    return normalized


def load_account_mode():
    return read_app_settings()["account"]["mode"]


def save_account_mode(mode):
    settings = read_app_settings()
    settings["account"]["mode"] = normalize_account_mode(mode)
    return save_app_settings(settings)["account"]["mode"]


def load_steam_browser_profile_prepared():
    return read_app_settings()["steam_browser"]["profile_prepared"]


def save_steam_browser_profile_prepared(prepared=True):
    settings = read_app_settings()
    settings["steam_browser"]["profile_prepared"] = bool(prepared)
    if not prepared:
        settings["steam_browser"]["pa_cookie_consent_prepared"] = False
    return save_app_settings(settings)["steam_browser"]["profile_prepared"]


def load_steam_pa_cookie_consent_prepared():
    return read_app_settings()["steam_browser"]["pa_cookie_consent_prepared"]


def save_steam_pa_cookie_consent_prepared(prepared=True):
    settings = read_app_settings()
    settings["steam_browser"]["pa_cookie_consent_prepared"] = bool(prepared)
    return save_app_settings(settings)["steam_browser"]["pa_cookie_consent_prepared"]


def load_pa_browser_profile_prepared():
    return read_app_settings()["pa_browser"]["profile_prepared"]


def save_pa_browser_profile_prepared(prepared=True):
    settings = read_app_settings()
    settings["pa_browser"]["profile_prepared"] = bool(prepared)
    return save_app_settings(settings)["pa_browser"]["profile_prepared"]


def load_saved_email():
    return read_app_settings()["account"]["email"]


def save_saved_email(email):
    settings = read_app_settings()
    settings["account"]["email"] = str(email).strip() if email else None
    return save_app_settings(settings)["account"]["email"]


def clear_saved_email():
    return save_saved_email(None)


def load_saved_session_last_known_valid():
    return read_app_settings()["session"]["saved_session_last_known_valid"]


def save_saved_session_last_known_valid(valid):
    settings = read_app_settings()
    settings["session"]["saved_session_last_known_valid"] = bool(valid)
    return save_app_settings(settings)["session"]["saved_session_last_known_valid"]


def load_ui_settings():
    return read_app_settings()["ui"]


def save_ui_settings(ui_settings):
    settings = read_app_settings()
    current_ui = settings.get("ui") if isinstance(settings.get("ui"), dict) else {}
    merged_ui = {
        **current_ui,
        **(ui_settings if isinstance(ui_settings, dict) else {}),
    }
    settings["ui"] = merged_ui
    return save_app_settings(settings)["ui"]


def save_polling_settings(selected, custom_range):
    ui = load_ui_settings()
    ui["polling"] = {
        "selected": str(selected),
        "custom_range": list(custom_range),
    }
    return save_ui_settings(ui)["polling"]


def save_purchase_delay_bounds(bounds):
    ui = load_ui_settings()
    ui["buy_delay"] = {
        "range": [float(bounds[0]), float(bounds[1])],
    }
    return save_ui_settings(ui)["buy_delay"]["range"]


def save_spend_cap(spend_cap):
    ui = load_ui_settings()
    ui["spend_cap"] = _coerce_spend_cap(spend_cap)
    return save_ui_settings(ui)["spend_cap"]


def save_buy_mode(enabled):
    ui = load_ui_settings()
    ui["buy_mode"] = bool(enabled)
    return save_ui_settings(ui)["buy_mode"]


def save_event_log_view(view):
    ui = load_ui_settings()
    ui["event_log_view"] = _normalize_event_log_view(view)
    return save_ui_settings(ui)["event_log_view"]


def account_mode_label(mode):
    return ACCOUNT_MODE_LABELS[normalize_account_mode(mode)]


def account_mode_detail(mode):
    return ACCOUNT_MODE_DETAILS[normalize_account_mode(mode)]
