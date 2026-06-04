from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

APP_SETTINGS_PATH = DATA_DIR / "app_settings.json"

SESSION_COOKIE_PATH = DATA_DIR / "session.json"

LOCAL_STATS_PATH = DATA_DIR / "local_stats.json"

BROWSER_PROFILES_DIR = DATA_DIR / "browser_profiles"
STEAM_MARKET_PROFILE_PATH = BROWSER_PROFILES_DIR / "steam-market"
STEAM_MARKET_DIAGNOSTIC_PROFILE_PATH = BROWSER_PROFILES_DIR / "steam-market-diagnostic"
