import asyncio
import random
import time
from collections import deque
from datetime import datetime

from bdo_marketplace_tools.market.api_handler import (
    DEFAULT_PURCHASE_DELAY_BOUNDS,
    MarketplaceAPIError,
)
from bdo_marketplace_tools.market.browser_auth import (
    BDO_SITE_BOOTSTRAP_URL,
    BrowserAuthError,
    acquire_market_cookies,
    clear_market_cookies_keep_steam_login,
    clear_steam_browser_profile_cookies,
    open_blank_steam_browser_diagnostic,
    prepare_steam_browser_profile,
)
from bdo_marketplace_tools.market.pricing import apply_price_rules, purchase_record_count, purchase_record_spend
from bdo_marketplace_tools.market.test_mode import SINGLE_ITEM_TEST_TARGET, check_single_item_stock
from bdo_marketplace_tools.services.update_checker import RELEASES_URL, check_for_update as run_update_check
from bdo_marketplace_tools.storage.app_settings import (
    STEAM_BROWSER_MODE,
    account_mode_detail,
    account_mode_label,
    default_app_settings,
    load_account_mode,
    load_last_seen_update_version,
    load_pa_browser_profile_prepared,
    load_saved_session_last_known_valid,
    load_steam_browser_profile_prepared,
    load_steam_pa_cookie_consent_prepared,
    load_ui_settings,
    load_update_check_on_startup,
    normalize_account_mode,
    save_account_mode,
    save_buy_mode,
    save_event_log_view,
    save_last_seen_update_version,
    save_pa_browser_profile_prepared,
    save_polling_settings,
    save_purchase_delay_bounds,
    save_saved_session_last_known_valid,
    save_spend_cap,
    save_steam_browser_profile_prepared,
    save_steam_pa_cookie_consent_prepared,
    save_update_check_on_startup,
)
from bdo_marketplace_tools.storage.credentials import CredentialStoreError, load_credentials
from bdo_marketplace_tools.storage.local_stats import DEFAULT_LOCAL_STATS, load_local_stats, save_local_stats
from bdo_marketplace_tools.storage.paths import LOCAL_STATS_PATH, PA_MARKET_PROFILE_PATH, STEAM_MARKET_PROFILE_PATH
from bdo_marketplace_tools.ui.display import APP_TITLE, EVENT_LEVEL_COLORS, format_duration
from bdo_marketplace_tools.version import APP_VERSION

LOCAL_DATA_PATH = LOCAL_STATS_PATH
DEFAULT_LOCAL_DATA = DEFAULT_LOCAL_STATS
DEBUG_OUTFIT_LISTING = [["debug-premium-outfit", "1", "2020000000"]]
MAX_ERROR_BACKOFF_MULTIPLIER = 6
EVENT_LOG_LIMIT = 20
SIMULATED_SESSION_EMAIL = "test-session@example.local"
BROWSER_VERIFICATION_MARKERS = (
    "browser verification",
    "manual browser verification",
    "requires browser",
)


def _load_local_data():
    return load_local_stats(path=LOCAL_DATA_PATH)


def _create_default_local_data():
    save_local_stats(DEFAULT_LOCAL_DATA, include_timestamp=False, path=LOCAL_DATA_PATH)


def _save_local_data(data):
    save_local_stats(data, path=LOCAL_DATA_PATH)


class BackgroundTasks:
    def __init__(self, api_handler, test_mode_enabled=False, persist_ui_settings=True):
        local_data = _load_local_data()
        self.api_handler = api_handler
        self.test_mode_enabled = bool(test_mode_enabled)
        self.persist_ui_settings = bool(persist_ui_settings)
        self.account_mode = load_account_mode()
        self.api_handler.account_mode = self.account_mode
        self.steam_browser_profile_prepared = load_steam_browser_profile_prepared()
        self.pa_browser_profile_prepared = load_pa_browser_profile_prepared()
        self.saved_session_last_known_valid = (
            load_saved_session_last_known_valid() if self.persist_ui_settings else False
        )
        self.steam_pa_cookie_consent_prepared = (
            load_steam_pa_cookie_consent_prepared() if self.persist_ui_settings else False
        )
        self.steam_auto_reauth_enabled = False
        self.checker_task = None
        self.single_item_test_checker_task = None
        self.login_checker_task = None
        self.checker_enabled = False
        self.checker_stop_requested = False
        self.single_item_test_checker_enabled = False
        self.single_item_test_purchase_enabled = False
        self.delay_choices = {
            "1": ("Fast", (3, 5)),
            "2": ("Balanced", (5, 10)),
            "3": ("Slow", (15, 30)),
        }
        ui_settings = load_ui_settings() if self.persist_ui_settings else default_app_settings()["ui"]
        polling_settings = ui_settings["polling"]
        self.delay = polling_settings["selected"]
        self.custom_delay_range = tuple(polling_settings["custom_range"])
        if self.delay == "custom":
            self.delay = self.matching_delay_choice(self.custom_delay_range) or "custom"
        elif self.delay not in self.delay_choices:
            self.delay = "3"
        self.purchase_delay_bounds = tuple(ui_settings["buy_delay"]["range"])
        self.events = deque(maxlen=EVENT_LOG_LIMIT)
        self.core_events = deque(maxlen=EVENT_LOG_LIMIT)
        self.ui_events = deque(maxlen=EVENT_LOG_LIMIT)
        self.event_log_view = ui_settings.get("event_log_view", "core")
        self.purchase_submission_enabled = bool(ui_settings["buy_mode"])
        self.buy_mode_resume_pending = False
        self.max_spend = ui_settings["spend_cap"]
        self.checker_started_at = None
        self.single_item_test_checker_started_at = None
        self.session_detected_outfits = 0
        self.session_successful_purchases = 0
        self.session_silver_spent = 0
        self.simulated_session_enabled = False
        self.debug_force_purchase_session_expired = False
        self.purchase_in_progress = False
        self.pending_auth_reset_reason = None
        self.browser_auth_lock = asyncio.Lock()
        self.consecutive_cycle_errors = 0
        self.single_item_test_cycle_errors = 0
        self.lifetime_successful_purchases = local_data["successful_purchases"]
        self.lifetime_silver_spent = local_data["silver_spent"]
        self.update_check_on_startup = (
            load_update_check_on_startup() if self.persist_ui_settings else True
        )
        self.last_seen_update_version = (
            load_last_seen_update_version() if self.persist_ui_settings else None
        )
        self.available_update_version = None
        self.update_check_completed = False
        self.update_check_in_progress = False

    def reload_lifetime_stats(self):
        local_data = _load_local_data()
        self.lifetime_successful_purchases = local_data["successful_purchases"]
        self.lifetime_silver_spent = local_data["silver_spent"]

    def save_local_data(self):
        _save_local_data(
            {
                "successful_purchases": self.lifetime_successful_purchases,
                "silver_spent": self.lifetime_silver_spent,
            }
        )

    def add_event(self, message, level="info", channel="core"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        style = EVENT_LEVEL_COLORS.get(level, EVENT_LEVEL_COLORS["info"])
        event = f"[dim]{timestamp}[/dim] [{style}]{message}[/{style}]"
        normalized_channel = str(channel or "core").strip().lower()
        if normalized_channel not in {"core", "ui"}:
            normalized_channel = "core"
        self.events.append(event)
        if normalized_channel == "ui":
            self.ui_events.append(event)
        else:
            self.core_events.append(event)

    def events_for_channel(self, channel):
        if str(channel or "").strip().lower() == "ui":
            return tuple(self.ui_events)
        return tuple(self.core_events)

    def set_event_log_view(self, view):
        normalized = str(view or "core").strip().lower()
        if normalized not in {"core", "ui"}:
            raise ValueError("Unknown event log view.")
        self.event_log_view = normalized
        if self.persist_ui_settings:
            self.event_log_view = save_event_log_view(normalized)
        return self.event_log_view

    def set_update_check_on_startup(self, enabled):
        self.update_check_on_startup = bool(enabled)
        if self.persist_ui_settings:
            self.update_check_on_startup = save_update_check_on_startup(self.update_check_on_startup)
        return self.update_check_on_startup

    async def check_for_update(self, manual=False):
        """Check GitHub for a newer published version (notify-only).

        Startup checks (``manual=False``) skip the remote lookup in test mode and when the
        user turned off the startup check, but still record the running version. A manual
        check always runs. The check is network-soft: it never raises, and on startup a
        failure stays silent. Returns the result, or ``None`` when the remote lookup was
        skipped.
        """
        if not manual:
            # Always record the running version at startup so the log shows the check ran,
            # even when the remote lookup is skipped (test mode or disabled).
            self.add_event(f"{APP_TITLE} v{APP_VERSION}.", "info")
        if not manual and (self.test_mode_enabled or not self.update_check_on_startup):
            return None
        if self.update_check_in_progress:
            return None

        self.update_check_in_progress = True
        try:
            result = await asyncio.to_thread(run_update_check)
        finally:
            self.update_check_in_progress = False

        if result.status == "update-available":
            self.update_check_completed = True
            self.available_update_version = result.latest_version
            self._announce_available_update(result.latest_version, manual=manual)
        elif result.status == "up-to-date":
            self.update_check_completed = True
            self.available_update_version = None
            if manual:
                self.add_event(
                    f"You are on the latest version ({result.current_version}).",
                    "info",
                    channel="ui",
                )
        elif manual:  # error, surfaced only for an explicit user-initiated check
            self.add_event(
                "Could not check for updates. Check your connection and try again.",
                "warning",
                channel="ui",
            )
        return result

    def _announce_available_update(self, latest_version, manual=False):
        message = (
            f"Update available: version {latest_version} (you have {APP_VERSION}). "
            f"Download it from {RELEASES_URL}"
        )
        if manual:
            self.add_event(message, "warning", channel="ui")
            return
        # Startup nudge: announce a given version once so launches are not spammed.
        if latest_version != self.last_seen_update_version:
            self.add_event(message, "warning")
            self._remember_seen_update_version(latest_version)

    def _remember_seen_update_version(self, version):
        self.last_seen_update_version = version
        if self.persist_ui_settings:
            self.last_seen_update_version = save_last_seen_update_version(version)

    def current_delay_label(self):
        if self.delay == "custom":
            matching_key = self.matching_delay_choice(self.custom_delay_range)
            if matching_key:
                return self.delay_choices[matching_key][0]
            return "Custom"
        return self.delay_choices[self.delay][0]

    def matching_delay_choice(self, bounds):
        bounds = tuple(bounds)
        for key, (_label, preset_bounds) in self.delay_choices.items():
            if tuple(preset_bounds) == bounds:
                return key
        return None

    def current_delay_bounds(self):
        if self.delay == "custom":
            return self.custom_delay_range
        return self.delay_choices[self.delay][1]

    def current_delay_range(self):
        low, high = self.current_delay_bounds()
        return f"{low}-{high}s"

    def purchase_delay_range(self):
        low, high = self.purchase_delay_bounds
        return f"{self._format_seconds(low)}-{self._format_seconds(high)}s"

    def recommended_delay_label(self):
        label, (low, high) = self.delay_choices["3"]
        return f"{label} ({low}-{high}s)"

    def set_custom_delay_range(self, low, high):
        low = int(low)
        high = int(high)
        if low <= 0 or high <= 0 or low > high:
            raise ValueError("Custom delay must use positive seconds with min less than or equal to max.")
        self.custom_delay_range = (low, high)
        self.delay = self.matching_delay_choice(self.custom_delay_range) or "custom"
        self._persist_polling_settings()

    def set_delay_choice(self, delay):
        delay = str(delay)
        if delay not in self.delay_choices:
            raise ValueError("Unknown polling delay preset.")
        self.delay = delay
        self.custom_delay_range = tuple(self.delay_choices[delay][1])
        self._persist_polling_settings()

    def set_custom_delay_choice(self):
        self.delay = "custom"
        self._persist_polling_settings()

    def set_purchase_delay_range(self, low, high):
        low = float(low)
        high = float(high)
        if low < 0 or high < 0 or low > high:
            raise ValueError("Purchase delay must use non-negative seconds with min less than or equal to max.")
        self.purchase_delay_bounds = (low, high)
        if self.persist_ui_settings:
            save_purchase_delay_bounds(self.purchase_delay_bounds)

    def set_spend_cap(self, spend_cap):
        spend_cap = int(spend_cap or 0)
        if spend_cap < 0:
            raise ValueError("Spend cap must be 0 or a positive integer.")
        self.max_spend = spend_cap or None
        if self.persist_ui_settings:
            save_spend_cap(self.max_spend)

    def set_purchase_submission_enabled(self, enabled):
        self.purchase_submission_enabled = bool(enabled)
        # Any time buy mode is on, there is nothing pending to auto-resume. This also means a
        # user explicitly enabling buy mode clears a stale auto-resume flag.
        if self.purchase_submission_enabled:
            self.buy_mode_resume_pending = False
        if self.persist_ui_settings:
            save_buy_mode(self.purchase_submission_enabled)
        return self.purchase_submission_enabled

    def pause_buy_mode_for_session_refresh(self, reason):
        if not self.purchase_submission_enabled:
            return False
        self.set_purchase_submission_enabled(False)
        # Remember that the *app* paused buy mode (not the user) so it can auto-resume once the
        # session is refreshed, keeping the monitor continuous across transient session expiry.
        self.buy_mode_resume_pending = True
        self.add_event(
            f"{reason} Buy mode paused; it will resume automatically once the session is refreshed.",
            "warning",
        )
        return True

    def resume_buy_mode_after_refresh(self):
        if not self.buy_mode_resume_pending:
            return False
        # set_purchase_submission_enabled(True) clears buy_mode_resume_pending.
        self.set_purchase_submission_enabled(True)
        self.add_event("Marketplace session refreshed; buy mode resumed.", "success")
        return True

    def _persist_polling_settings(self):
        if self.persist_ui_settings:
            save_polling_settings(self.delay, self.custom_delay_range)

    def _set_saved_session_last_known_valid(self, valid):
        self.saved_session_last_known_valid = bool(valid)
        if self.persist_ui_settings:
            self.saved_session_last_known_valid = save_saved_session_last_known_valid(valid)
        return self.saved_session_last_known_valid

    def _api_has_session_cookies(self):
        if hasattr(self.api_handler, "has_session_cookies"):
            return self.api_handler.has_session_cookies()
        session = getattr(self.api_handler, "session", None)
        return bool(getattr(session, "cookies", None))

    async def _saved_session_is_valid(self):
        if not self._api_has_session_cookies():
            return False
        try:
            status = await self._check_session_expired()
        except MarketplaceAPIError:
            return False

        if status == 0:
            self.api_handler.login_status = True
            self._set_saved_session_last_known_valid(True)
            if self.uses_steam_browser_session():
                self.steam_auto_reauth_enabled = True
            self.start_login_status_checker()
            self.resume_buy_mode_after_refresh()
            return True

        self.api_handler.login_status = False
        return False

    def _format_seconds(self, value):
        value = float(value)
        if value.is_integer():
            return str(int(value))
        return f"{value:g}"

    def runtime_label(self):
        started_at = None
        if self.checker_enabled:
            started_at = self.checker_started_at
        elif self.single_item_test_checker_enabled:
            started_at = self.single_item_test_checker_started_at

        if started_at is None:
            return "00:00:00"
        return format_duration(time.monotonic() - started_at)

    def monitor_running(self):
        return self.checker_enabled or self.single_item_test_checker_enabled

    def uses_steam_browser_session(self):
        return self.account_mode == STEAM_BROWSER_MODE

    def account_mode_label(self):
        return account_mode_label(self.account_mode)

    def account_mode_detail(self):
        return account_mode_detail(self.account_mode)

    def steam_browser_profile_needs_setup(self):
        return self.uses_steam_browser_session() and not self.steam_browser_profile_prepared

    def steam_auto_reauth_available(self):
        return self.uses_steam_browser_session() and (
            self.steam_browser_profile_prepared or self.steam_auto_reauth_enabled
        )

    def _set_steam_pa_cookie_consent_prepared(self, prepared):
        self.steam_pa_cookie_consent_prepared = bool(prepared)
        if self.persist_ui_settings:
            self.steam_pa_cookie_consent_prepared = save_steam_pa_cookie_consent_prepared(prepared)
        return self.steam_pa_cookie_consent_prepared

    def _set_pa_browser_profile_prepared(self, prepared):
        self.pa_browser_profile_prepared = bool(prepared)
        if self.persist_ui_settings:
            self.pa_browser_profile_prepared = save_pa_browser_profile_prepared(prepared)
        return self.pa_browser_profile_prepared

    def set_account_mode(self, mode):
        normalized = normalize_account_mode(mode)
        if normalized != self.account_mode:
            self.steam_auto_reauth_enabled = False
        self.account_mode = save_account_mode(normalized)
        self.api_handler.account_mode = self.account_mode
        return self.account_mode

    async def change_account_mode(self, mode):
        normalized = normalize_account_mode(mode)
        previous_mode = self.account_mode
        self.account_mode = save_account_mode(normalized)
        self.api_handler.account_mode = self.account_mode
        if normalized != previous_mode:
            self.steam_auto_reauth_enabled = False
            await self.reset_authentication_context("Login method changed")
            return True
        return False

    async def reset_authentication_context(self, reason):
        await self.stop_login_status_checker()
        self.steam_auto_reauth_enabled = False
        self.set_purchase_submission_enabled(False)

        if self.purchase_in_progress:
            self.pending_auth_reset_reason = reason
            self.checker_stop_requested = True
            self.add_event(
                f"{reason}. Current purchase chain will finish, then the monitor will stop and the marketplace session will be cleared.",
                "warning",
            )
            return False

        await self.stop_checker()
        await self.stop_single_item_test_checker()
        self._clear_marketplace_session(reason)
        return True

    def _complete_pending_auth_reset_if_ready(self):
        if self.pending_auth_reset_reason and not self.purchase_in_progress:
            self.checker_stop_requested = True
            self._clear_marketplace_session(self.pending_auth_reset_reason)
            return True
        return False

    def _clear_marketplace_session(self, reason):
        self.pending_auth_reset_reason = None
        self.steam_auto_reauth_enabled = False
        self.set_purchase_submission_enabled(False)
        self.simulated_session_enabled = False
        if hasattr(self.api_handler, "clear_session"):
            self.api_handler.clear_session()
        else:
            self.api_handler.login_status = False
        self._set_saved_session_last_known_valid(False)
        self.add_event(f"{reason}. Marketplace session cleared. Refresh Session before buying.", "warning")

    def monitor_status_label(self):
        if self.single_item_test_checker_enabled:
            return "Test Scan"
        if self.checker_enabled:
            return "Running"
        return "Stopped"

    def monitor_mode_label(self):
        if self.single_item_test_checker_enabled:
            return "Test buy" if self.single_item_test_purchase_enabled else "Single item"
        return "Buy mode" if self.purchase_submission_enabled else "Watch only"

    async def start_checker(self):
        if self.purchase_submission_enabled and not self.api_handler.login_status:
            return False

        if self.single_item_test_checker_task is not None and not self.single_item_test_checker_task.done():
            return False

        if self.checker_task is not None and not self.checker_task.done():
            self.checker_enabled = True
            return False

        self.checker_stop_requested = False
        self.checker_started_at = time.monotonic()
        self.checker_task = asyncio.create_task(self.checker())
        self.checker_task.add_done_callback(self._handle_checker_done)
        self.checker_enabled = True
        return True

    async def start_single_item_test_checker(self, allow_purchase=False):
        if not self.test_mode_enabled:
            return False

        if self.checker_task is not None and not self.checker_task.done():
            return False

        if self.single_item_test_checker_task is not None and not self.single_item_test_checker_task.done():
            self.single_item_test_checker_enabled = True
            return False

        self.single_item_test_checker_started_at = time.monotonic()
        self.single_item_test_purchase_enabled = bool(allow_purchase)
        self.single_item_test_checker_task = asyncio.create_task(self.single_item_test_checker())
        self.single_item_test_checker_task.add_done_callback(self._handle_single_item_test_checker_done)
        self.single_item_test_checker_enabled = True
        return True

    def _handle_checker_done(self, task):
        if task.cancelled():
            return

        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return

        if exc is not None:
            self.add_event(f"Monitor stopped after an unexpected error: {exc}", "error")

        self.checker_enabled = False
        self.checker_stop_requested = False
        self.checker_started_at = None
        if self.checker_task is task:
            self.checker_task = None

    def _handle_single_item_test_checker_done(self, task):
        if task.cancelled():
            return

        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return

        if exc is not None:
            self.add_event(f"Single-item test monitor stopped after an unexpected error: {exc}", "error")

        self.single_item_test_checker_enabled = False
        self.single_item_test_purchase_enabled = False
        self.single_item_test_checker_started_at = None
        if self.single_item_test_checker_task is task:
            self.single_item_test_checker_task = None

    async def stop_checker(self):
        was_running = bool(self.checker_task and not self.checker_task.done())
        self.checker_stop_requested = True
        if self.checker_task and not self.checker_task.done():
            self.checker_task.cancel()
            try:
                await self.checker_task
            except asyncio.CancelledError:
                pass

        self.checker_enabled = False
        self.checker_stop_requested = False
        self.checker_started_at = None
        self.checker_task = None
        return was_running

    async def stop_single_item_test_checker(self):
        was_running = bool(self.single_item_test_checker_task and not self.single_item_test_checker_task.done())
        if self.single_item_test_checker_task and not self.single_item_test_checker_task.done():
            self.single_item_test_checker_task.cancel()
            try:
                await self.single_item_test_checker_task
            except asyncio.CancelledError:
                pass

        self.single_item_test_checker_enabled = False
        self.single_item_test_purchase_enabled = False
        self.single_item_test_checker_started_at = None
        self.single_item_test_checker_task = None
        return was_running

    def start_login_status_checker(self):
        if self.login_checker_task is None or self.login_checker_task.done():
            self.login_checker_task = asyncio.create_task(self.login_status_checker())

    async def stop_login_status_checker(self):
        if self.login_checker_task and not self.login_checker_task.done():
            self.login_checker_task.cancel()
            try:
                await self.login_checker_task
            except asyncio.CancelledError:
                pass
        self.login_checker_task = None

    async def checker(self):
        try:
            while not self.checker_stop_requested:
                try:
                    buy_list = await self.api_handler.check_stock()
                    await self.process_detected_outfits(buy_list)
                    self.consecutive_cycle_errors = 0
                except Exception as exc:
                    self.consecutive_cycle_errors += 1
                    self.add_event(f"Monitor cycle failed: {exc}", "error")

                if self._complete_pending_auth_reset_if_ready() or self.checker_stop_requested:
                    break

                sleep_duration = self.next_sleep_duration()
                await asyncio.sleep(sleep_duration)
        except asyncio.CancelledError:
            raise

    async def single_item_test_checker(self):
        if not self.test_mode_enabled:
            self.add_event("Single-item test monitor is only available in test mode.", "warning")
            return

        item_name = SINGLE_ITEM_TEST_TARGET["name"]
        try:
            while True:
                try:
                    buy_list = await check_single_item_stock(self.api_handler, SINGLE_ITEM_TEST_TARGET)
                    await self.process_detected_outfits(
                        buy_list,
                        allow_purchase=self.single_item_test_purchase_enabled,
                        item_noun="test item",
                        adjust_pricing=False,
                    )
                    self.single_item_test_cycle_errors = 0
                except Exception as exc:
                    self.single_item_test_cycle_errors += 1
                    self.add_event(f"{item_name} test scan failed: {exc}", "error")

                sleep_duration = self.next_single_item_test_sleep_duration()
                await asyncio.sleep(sleep_duration)
        except asyncio.CancelledError:
            raise

    def next_sleep_duration(self):
        return self._next_sleep_duration(self.consecutive_cycle_errors)

    def next_single_item_test_sleep_duration(self):
        return self._next_sleep_duration(self.single_item_test_cycle_errors)

    def _next_sleep_duration(self, cycle_errors):
        low, high = self.current_delay_bounds()
        if cycle_errors <= 0:
            return random.uniform(low, high)

        multiplier = min(MAX_ERROR_BACKOFF_MULTIPLIER, 1 + cycle_errors)
        return random.uniform(low * multiplier, high * multiplier)

    async def process_detected_outfits(self, buy_list, allow_purchase=None, item_noun="outfit", adjust_pricing=True):
        if not buy_list:
            return

        detected_count = self._detected_outfit_count(buy_list)
        self.session_detected_outfits += detected_count
        purchase_enabled = self.purchase_submission_enabled if allow_purchase is None else allow_purchase
        detected_label = f"{detected_count} available {self._pluralize(item_noun, detected_count)}"
        subject = item_noun[:1].upper() + item_noun[1:]

        if purchase_enabled:
            self.add_event(f"{subject} detected: {detected_label}. Attempting purchase.", "success")
            await self.buy_item(buy_list, adjust_pricing=adjust_pricing)
        else:
            self.add_event(f"{subject} detected: {detected_label}.", "success")

    def _detected_outfit_count(self, buy_list):
        return sum(int(item[1]) for item in buy_list)

    def _pluralize(self, noun, count):
        if count == 1:
            return noun
        return f"{noun}s"

    async def debug_fake_outfit_detection(self):
        if not self.test_mode_enabled:
            return False

        await self.process_detected_outfits(DEBUG_OUTFIT_LISTING, allow_purchase=False)
        return True

    async def debug_simulate_purchase_success(self):
        if not self.test_mode_enabled:
            return False

        detected_count = self._detected_outfit_count(DEBUG_OUTFIT_LISTING)
        self.session_detected_outfits += detected_count
        self.add_event(f"Outfit detected: {detected_count} available outfits. Simulating purchase.", "success")

        adjusted_buy_list = await self.adjust_prices(DEBUG_OUTFIT_LISTING)
        self.record_purchase_summary(self._simulated_purchase_summary(adjusted_buy_list, "Simulated purchase succeeded"))
        return True

    def debug_invalidate_marketplace_session(self):
        if not self.test_mode_enabled:
            return False

        self.simulated_session_enabled = False
        self.debug_force_purchase_session_expired = True
        self._set_saved_session_last_known_valid(False)
        if self.uses_steam_browser_session() and getattr(self.api_handler, "login_status", False):
            self.steam_auto_reauth_enabled = True
        return True

    def debug_toggle_steam_auto_reauth(self):
        if not self.test_mode_enabled or not self.uses_steam_browser_session():
            return None

        self.steam_auto_reauth_enabled = not self.steam_auto_reauth_enabled
        return self.steam_auto_reauth_enabled

    async def debug_run_reauthentication_check(self):
        if not self.test_mode_enabled:
            return False

        self.add_event("Simulated purchase response: login session expired.", "warning")
        recovered = await self._recover_purchase_session_for_retry(force_browser_refresh=True)
        if recovered:
            self.debug_force_purchase_session_expired = False
        return recovered

    async def debug_run_session_check_now(self):
        """Run one iteration of the production periodic session checker on demand (test mode).

        This is the real `_run_one_session_check` path: it detects expiry (honoring the "Expire
        Session" override) and, if expired, runs `handle_expired_session` exactly as the idle bot
        would. Use "Expire Session" first to exercise the detect -> auto re-auth flow.
        """
        if not self.test_mode_enabled:
            return None

        self.add_event("Test: running the periodic session check now.", "info")
        result = await self._run_one_session_check()
        if result and self.debug_force_purchase_session_expired:
            # A forced-expiry run that recovered: drop the override so later checks see the real
            # session instead of staying permanently "expired".
            self.debug_force_purchase_session_expired = False
        return result

    async def debug_open_blank_browser_diagnostic(self):
        if not self.test_mode_enabled:
            return False

        try:
            await open_blank_steam_browser_diagnostic(status_callback=self._browser_auth_status)
        except BrowserAuthError as exc:
            self.add_event(f"Blank browser diagnostic failed: {exc}", "error")
            return False

        self.add_event("Blank browser diagnostic closed.", "info")
        return True

    def reset_steam_initial_setup_status(self):
        """Mark Steam initial setup incomplete and clear the one-time consent flag.

        Ungated maintenance action used by App Settings; the test-mode debug
        control delegates here.
        """
        self.steam_browser_profile_prepared = save_steam_browser_profile_prepared(False)
        self._set_steam_pa_cookie_consent_prepared(False)
        self.steam_auto_reauth_enabled = False
        self.add_event("Initial Steam setup status reset to incomplete.", "warning")
        return True

    def debug_clear_steam_initial_setup_status(self):
        if not self.test_mode_enabled:
            return False

        return self.reset_steam_initial_setup_status()

    async def debug_dump_cookies_keep_steam_login(self):
        if not self.test_mode_enabled:
            return False

        if not self.uses_steam_browser_session():
            self.add_event(
                "Dump cookies (keep Steam login) is only available in Steam Account mode.",
                "warning",
            )
            return False

        try:
            cleared_count = await clear_market_cookies_keep_steam_login(profile_path=STEAM_MARKET_PROFILE_PATH)
        except BrowserAuthError as exc:
            self.add_event(f"Test cookie dump failed: {exc}", "error")
            return False

        # Re-arm the re-auth flow so the next refresh runs the full cookie-box + Steam-button path,
        # while keeping the Steam login and the saved Steam setup so no Steam re-login is needed.
        self._set_steam_pa_cookie_consent_prepared(False)
        self._set_saved_session_last_known_valid(False)
        self.add_event(
            f"Test mode: cleared {cleared_count} non-Steam cookies (market/PA/consent); kept Steam login. "
            "Run Reauth Check to exercise the full re-auth flow.",
            "warning",
        )
        return True

    async def clear_browser_session_cookies(self):
        """Clear cookies from the app-owned browser profile for the active login method.

        Ungated maintenance action used by App Settings for recovering a stuck
        login. Clears the Steam profile in Steam mode (and resets Steam setup
        state) or the Pearl Abyss profile in PA mode.
        """
        steam_mode = self.uses_steam_browser_session()
        profile_path = STEAM_MARKET_PROFILE_PATH if steam_mode else PA_MARKET_PROFILE_PATH
        try:
            cleared_count = await clear_steam_browser_profile_cookies(profile_path=profile_path)
        except BrowserAuthError as exc:
            self.add_event(f"Browser cookie clear failed: {exc}", "error")
            return False

        if steam_mode:
            self.steam_browser_profile_prepared = save_steam_browser_profile_prepared(False)
            self._set_steam_pa_cookie_consent_prepared(False)
            self.steam_auto_reauth_enabled = False
        else:
            self._set_pa_browser_profile_prepared(False)
        self.add_event(
            f"Browser cookies cleared from the app-owned {self.account_mode_label()} profile ({cleared_count} cookies).",
            "warning",
        )
        return True

    async def debug_clear_steam_browser_cookies(self):
        if not self.test_mode_enabled:
            return False

        try:
            cleared_count = await clear_steam_browser_profile_cookies()
        except BrowserAuthError as exc:
            self.add_event(f"Steam browser cookie clear failed: {exc}", "error")
            return False

        self.steam_browser_profile_prepared = save_steam_browser_profile_prepared(False)
        self._set_steam_pa_cookie_consent_prepared(False)
        self.steam_auto_reauth_enabled = False
        self.add_event(f"Steam browser cookies cleared from the app-owned profile ({cleared_count} cookies).", "warning")
        return True

    async def prepare_steam_browser_profile(self, *, allow_inactive_mode=False):
        if not self.uses_steam_browser_session() and not allow_inactive_mode:
            self.add_event("Switch to Steam Account before running initial Steam setup.", "warning")
            return False

        if self.steam_browser_profile_prepared:
            self.add_event("Initial Steam browser setup is already complete.", "info")
            return True

        try:
            await prepare_steam_browser_profile(status_callback=self._browser_auth_status)
        except BrowserAuthError as exc:
            self.add_event(f"Initial Steam browser setup failed: {exc}", "error")
            return False

        self.steam_browser_profile_prepared = save_steam_browser_profile_prepared(True)
        self.steam_auto_reauth_enabled = True
        self.add_event("Initial Steam browser setup saved. Refresh Session can now open the market login.", "success")
        return True

    async def _recover_purchase_session_for_retry(self, *, force_browser_refresh=False):
        self.add_event("Login session expired. Attempting to re-authenticate.", "warning")

        if self.uses_steam_browser_session():
            refreshed = await self.refresh_browser_session(force_refresh=force_browser_refresh)
            if refreshed:
                self.add_event("Re-authentication succeeded. Retrying purchase request.", "success")
                return True

            self.add_event("Re-authentication failed. Purchase retry skipped.", "error")
            return False

        if await self.refresh_pa_browser_session(force_refresh=force_browser_refresh):
            self._set_saved_session_last_known_valid(True)
            self.add_event("Re-authentication succeeded. Retrying purchase request.", "success")
            return True

        self._set_saved_session_last_known_valid(False)
        self.pause_buy_mode_for_session_refresh("Re-authentication failed.")
        self.add_event("Re-authentication failed.", "error")
        return False

    def set_simulated_session(self, enabled):
        if not self.test_mode_enabled:
            return False

        self.simulated_session_enabled = bool(enabled)
        self.api_handler.login_status = bool(enabled)
        if enabled and not getattr(self.api_handler, "email", None):
            self.api_handler.email = SIMULATED_SESSION_EMAIL
        if not enabled and getattr(self.api_handler, "email", None) == SIMULATED_SESSION_EMAIL:
            self.api_handler.email = None
        if not enabled:
            self.set_purchase_submission_enabled(False)
        return True

    def _simulated_purchase_summary(self, buy_list, label="Test-mode purchase simulated"):
        purchase_records = []
        for item_id, stock, price in buy_list:
            purchase_records.append(
                {
                    "item_id": item_id,
                    "price": int(price),
                    "count": int(stock),
                    "result_code": 0,
                }
            )

        purchased_count = purchase_record_count(purchase_records)
        return {
            "purchase_records": purchase_records,
            "events": [
                {
                    "level": "success",
                    "message": f"{label} for {purchased_count} outfit.",
                }
            ],
        }

    async def buy_item(self, buy_list, adjust_pricing=True):
        self.purchase_in_progress = True
        if adjust_pricing:
            updated_buy_list = await self.adjust_prices(buy_list)
        else:
            updated_buy_list = self._normalize_buy_list(buy_list)
        try:
            capped_buy_list = self._apply_spend_cap(updated_buy_list)

            if not capped_buy_list:
                self.add_event("Purchase skipped: spend cap would be exceeded.", "warning")
                return

            if self.simulated_session_enabled:
                self.record_purchase_summary(self._simulated_purchase_summary(capped_buy_list))
                return

            try:
                summary = await self.api_handler.buy_item(
                    capped_buy_list,
                    purchase_delay_bounds=self.purchase_delay_bounds,
                )
            except MarketplaceAPIError as exc:
                if not self.uses_steam_browser_session() and self._requires_browser_verification(exc):
                    self.pause_buy_mode_for_session_refresh("Purchase authentication failed.")
                self.add_event(f"Purchase request failed: {exc}", "error")
                return

            if not self.uses_steam_browser_session() and not summary.get("purchase_records"):
                pa_auth_retry_needed = (
                    self._purchase_summary_requires_browser_verification(summary)
                    or self._purchase_summary_has_expired_session(summary)
                    or self._purchase_summary_has_auth_failure(summary)
                )
                if pa_auth_retry_needed and await self._recover_purchase_session_for_retry():
                    try:
                        summary = await self.api_handler.buy_item(
                            capped_buy_list,
                            purchase_delay_bounds=self.purchase_delay_bounds,
                        )
                    except MarketplaceAPIError as exc:
                        if self._requires_browser_verification(exc):
                            self.pause_buy_mode_for_session_refresh("Purchase authentication failed.")
                        self.add_event(f"Purchase retry failed: {exc}", "error")
                        return

            if not self.uses_steam_browser_session() and self._purchase_summary_has_auth_failure(summary):
                self.pause_buy_mode_for_session_refresh("Purchase authentication failed.")

            if self.uses_steam_browser_session() and self._purchase_summary_has_expired_session(summary):
                if await self._recover_purchase_session_for_retry():
                    try:
                        summary = await self.api_handler.buy_item(
                            capped_buy_list,
                            purchase_delay_bounds=self.purchase_delay_bounds,
                        )
                    except MarketplaceAPIError as exc:
                        self.add_event(f"Purchase retry failed: {exc}", "error")
                        return

            self.record_purchase_summary(summary)
        finally:
            self.purchase_in_progress = False
            self._complete_pending_auth_reset_if_ready()

    def _purchase_summary_has_expired_session(self, summary):
        for result in summary.get("results", []):
            if isinstance(result, dict) and result.get("result_code") == 2000:
                return True
        return False

    def _purchase_summary_requires_browser_verification(self, summary):
        for event in summary.get("events", []):
            if isinstance(event, dict):
                message = event.get("message", "")
            else:
                message = event
            if self._requires_browser_verification(message):
                return True
        return False

    def _purchase_summary_has_auth_failure(self, summary):
        if summary.get("auth_failed") is True:
            return True

        for event in summary.get("events", []):
            if isinstance(event, dict):
                message = event.get("message", "")
            else:
                message = event
            normalized = str(message).lower()
            if any(
                marker in normalized
                for marker in (
                    "re-authentication failed",
                    "login session is invalid",
                    "refresh session before buying",
                    "browser verification",
                    "requires browser",
                )
            ):
                return True
        return False

    def _normalize_buy_list(self, buy_list):
        return [[str(item_id), str(stock), str(price)] for item_id, stock, price in buy_list]

    def record_purchase_summary(self, summary):
        purchase_records = summary.get("purchase_records", [])
        purchased_count = purchase_record_count(purchase_records)
        silver_spent = purchase_record_spend(purchase_records)

        if purchased_count > 0 or silver_spent > 0:
            self.session_successful_purchases += purchased_count
            self.session_silver_spent += silver_spent
            self.lifetime_successful_purchases += purchased_count
            self.lifetime_silver_spent += silver_spent
            self.save_local_data()

        summary_events = summary.get("events", [])
        for event in summary_events:
            if isinstance(event, dict):
                self.add_event(event.get("message", ""), event.get("level", "info"))
            else:
                self.add_event(event, "success" if "succeeded" in event else "warning")

        if purchased_count == 0 and not summary_events:
            self.add_event("Purchase attempt completed without a successful request.", "warning")

    def _apply_spend_cap(self, buy_list):
        if self.max_spend is None:
            return buy_list

        capped = []
        remaining = self.max_spend - self.session_silver_spent
        if remaining <= 0:
            return capped

        for item_id, stock, price in buy_list:
            item_price = int(price)
            if item_price <= 0:
                continue
            allowed_count = min(int(stock), remaining // item_price)
            if allowed_count > 0:
                capped.append([item_id, str(allowed_count), price])
                remaining -= allowed_count * item_price
            if remaining <= 0:
                break

        return capped

    async def adjust_prices(self, buy_list):
        modified_list, fallback_items = apply_price_rules(buy_list)
        if fallback_items:
            self.add_event(f"Fallback pricing applied to {len(fallback_items)} outfit listings.", "warning")
        return modified_list

    async def login(self):
        session_check_error = None
        try:
            status = await self.api_handler.is_session_expired()
        except MarketplaceAPIError as exc:
            self.api_handler.login_status = False
            session_check_error = exc
            status = -1

        if status == 0:
            self.api_handler.login_status = True
            self._set_saved_session_last_known_valid(True)
            if self.uses_steam_browser_session():
                self.steam_auto_reauth_enabled = True
            self.add_event("Existing marketplace session is valid.", "success")
            self.start_login_status_checker()
            self.resume_buy_mode_after_refresh()
            return

        if self.uses_steam_browser_session():
            await self.refresh_browser_session(session_check_error=session_check_error)
            return

        if not await self.refresh_pa_browser_session(session_check_error=session_check_error):
            self.pause_buy_mode_for_session_refresh("Pearl Abyss Account refresh failed.")

    def _requires_browser_verification(self, exc):
        message = str(exc).lower()
        return any(marker in message for marker in BROWSER_VERIFICATION_MARKERS)

    def _pa_browser_login_credentials(self):
        try:
            saved_email, saved_password = load_credentials()
        except CredentialStoreError as exc:
            return None, None, exc

        if saved_email:
            self.api_handler.email = saved_email
        if saved_password:
            self.api_handler.password = saved_password
        return saved_email, saved_password, None

    async def refresh_pa_browser_session(
        self,
        session_check_error=None,
        login_error=None,
        *,
        auto_pa_login=None,
        force_refresh=False,
    ):
        async with self.browser_auth_lock:
            if not force_refresh and await self._saved_session_is_valid():
                return True

            details = []
            if session_check_error:
                details.append(f"Session check failed: {session_check_error}.")
            if login_error:
                details.append(f"Pearl Abyss Account login needs browser verification: {login_error}.")

            email, password, credential_error = self._pa_browser_login_credentials()
            saved_credentials_ready = bool(email and password)
            auto_submit_credentials = saved_credentials_ready if auto_pa_login is None else bool(auto_pa_login)
            auto_submit_credentials = auto_submit_credentials and saved_credentials_ready

            if credential_error:
                details.append(f"Saved credentials unavailable: {credential_error}.")
            if auto_submit_credentials:
                details.append("Opening Pearl Abyss Account browser session; saved credentials will be submitted automatically.")
            else:
                details.append("Opening Pearl Abyss Account browser session for manual login.")
            self.add_event(" ".join(details), "warning")

            try:
                bootstrap_url = None
                if not self.pa_browser_profile_prepared:
                    bootstrap_url = BDO_SITE_BOOTSTRAP_URL

                cookies = await acquire_market_cookies(
                    status_callback=self._browser_auth_status,
                    auto_steam_login=False,
                    auto_pa_login=auto_submit_credentials,
                    pa_email=email if auto_submit_credentials else None,
                    pa_password=password if auto_submit_credentials else None,
                    profile_path=PA_MARKET_PROFILE_PATH,
                    bootstrap_url=bootstrap_url,
                    account_label="Pearl Abyss Account",
                )
            except BrowserAuthError as exc:
                self.api_handler.login_status = False
                self._set_saved_session_last_known_valid(False)
                self.add_event(f"Pearl Abyss Account browser refresh failed: {exc}", "error")
                return False

            try:
                session_valid = await self.api_handler.validate_and_save_imported_session(cookies)
            except MarketplaceAPIError as exc:
                self.api_handler.login_status = False
                self._set_saved_session_last_known_valid(False)
                self.add_event(f"Pearl Abyss Account browser session validation failed: {exc}", "error")
                return False

            if session_valid:
                self.api_handler.login_status = True
                self._set_pa_browser_profile_prepared(True)
                self._set_saved_session_last_known_valid(True)
                self.start_login_status_checker()
                self.add_event("Pearl Abyss Account browser session validated and saved.", "success")
                self.resume_buy_mode_after_refresh()
                return True

            self.api_handler.login_status = False
            self._set_saved_session_last_known_valid(False)
            self.add_event(
                "Pearl Abyss Account browser session validation failed. Complete login in the browser and retry.",
                "error",
            )
            return False

    async def refresh_browser_session(self, session_check_error=None, *, auto_steam_login=None, force_refresh=False):
        async with self.browser_auth_lock:
            if not force_refresh and await self._saved_session_is_valid():
                return True

            if self.steam_browser_profile_needs_setup():
                self.add_event("Initial Steam browser setup is required before the market login refresh.", "warning")
                prepared = await self.prepare_steam_browser_profile()
                if not prepared:
                    self.api_handler.login_status = False
                    self._set_saved_session_last_known_valid(False)
                    return False

            if auto_steam_login is None:
                auto_steam_login = self.steam_auto_reauth_available()

            if session_check_error:
                self.add_event(
                    f"Session check failed: {session_check_error}. Opening Steam Account browser session.",
                    "warning",
                )
            elif auto_steam_login:
                self.add_event("Opening Steam Account browser session for automatic re-authentication.", "info")
            else:
                self.add_event("Opening Steam Account browser session for manual login.", "info")

            try:
                handle_pa_cookie_consent = bool(auto_steam_login and not self.steam_pa_cookie_consent_prepared)
                cookies = await acquire_market_cookies(
                    status_callback=self._browser_auth_status,
                    auto_steam_login=auto_steam_login,
                    handle_pa_cookie_consent=handle_pa_cookie_consent,
                    pa_cookie_consent_callback=self._set_steam_pa_cookie_consent_prepared,
                )
            except BrowserAuthError as exc:
                self.api_handler.login_status = False
                self._set_saved_session_last_known_valid(False)
                # Self-heal: if an auto-login refresh failed while the one-time PA cookie-consent
                # probe was being skipped (prepared flag set), re-arm it. A "prepared" flag set
                # without actually dismissing the Cookiebot banner would otherwise let the banner
                # block the Steam login button on every future refresh.
                if auto_steam_login and self.steam_pa_cookie_consent_prepared:
                    self._set_steam_pa_cookie_consent_prepared(False)
                self.add_event(f"Steam Account refresh failed: {exc}", "error")
                return False

            try:
                session_valid = await self.api_handler.validate_and_save_imported_session(cookies)
            except MarketplaceAPIError as exc:
                self.api_handler.login_status = False
                self._set_saved_session_last_known_valid(False)
                self.add_event(f"Steam Account session validation failed: {exc}", "error")
                return False

            if session_valid:
                self.api_handler.login_status = True
                self._set_saved_session_last_known_valid(True)
                self.steam_auto_reauth_enabled = True
                self.add_event("Steam Account session validated and saved.", "success")
                self.start_login_status_checker()
                self.resume_buy_mode_after_refresh()
                return True

            self.api_handler.login_status = False
            self._set_saved_session_last_known_valid(False)
            self.add_event("Steam Account session validation failed. Complete login in the browser and retry.", "error")
            return False

    def _browser_auth_status(self, message, level="info"):
        self.add_event(message, level)

    async def initial_login_check(self):
        if not self.saved_session_last_known_valid:
            self.api_handler.login_status = False
            if self.uses_steam_browser_session():
                self.add_event(
                    "No previously validated Steam Account session is saved. Refresh Session to open the login browser.",
                    "warning",
                )
            else:
                self.add_event(
                    "No previously validated marketplace session is saved. Refresh Session to open the login browser.",
                    "warning",
                )
            return

        if not self._api_has_session_cookies():
            self.api_handler.login_status = False
            self._set_saved_session_last_known_valid(False)
            self.add_event("No saved marketplace session cookies found. Refresh Session to log in.", "warning")
            return

        try:
            status = await self.api_handler.is_session_expired()
        except MarketplaceAPIError as exc:
            self.api_handler.login_status = False
            self.add_event(f"Saved marketplace session check failed: {exc}", "warning")
            return

        if status == 0:
            self.api_handler.login_status = True
            self._set_saved_session_last_known_valid(True)
            if self.uses_steam_browser_session():
                self.steam_auto_reauth_enabled = True
            self.start_login_status_checker()
            self.add_event("Saved marketplace session is valid.", "success")
        else:
            self.api_handler.login_status = False
            self._set_saved_session_last_known_valid(False)
            if self.uses_steam_browser_session():
                self.add_event(
                    "Saved Steam Account session is invalid or expired. Refresh Session to open the login browser.",
                    "warning",
                )
            else:
                self.add_event(
                    "Saved marketplace session is invalid or expired. Refresh Session to open the login browser.",
                    "warning",
                )

    async def login_status_checker(self):
        try:
            while True:
                await asyncio.sleep(random.uniform(1800, 2400))
                if not await self._run_one_session_check():
                    break
        except asyncio.CancelledError:
            raise

    async def _check_session_expired(self):
        # Test-only override: "Expire Session" sets this flag so the production session check below
        # reports expiry without a live API call, letting the real detect -> re-auth path be tested.
        if self.test_mode_enabled and self.debug_force_purchase_session_expired:
            return -1
        return await self.api_handler.is_session_expired()

    async def _run_one_session_check(self):
        """Run one periodic session check and react to it.

        Returns True to keep the periodic checker running (session valid, recovered, or a transient
        check error) and False to stop it (session expired and re-authentication failed). The "Run
        Session Check" test control calls this same method so the test path is the production path.
        """
        try:
            status = await self._check_session_expired()
        except MarketplaceAPIError as exc:
            self.add_event(f"Session check failed: {exc}", "error")
            return True

        if status == -1:
            return await self.handle_expired_session()

        self.api_handler.login_status = True
        self.add_event("Session still valid.")
        return True

    async def handle_expired_session(self):
        self.api_handler.login_status = False
        if self.uses_steam_browser_session():
            if self.steam_auto_reauth_available():
                self.add_event("Session expired. Attempting automatic Steam Account re-authentication.", "warning")
                if await self.refresh_browser_session(auto_steam_login=True):
                    self.add_event("Session expired. Re-authentication successful.", "success")
                    return True

            if self.purchase_submission_enabled:
                self.set_purchase_submission_enabled(False)
                self.add_event(
                    "Session expired. Steam Account refresh required; buy mode paused.",
                    "warning",
                )
            else:
                self.add_event(
                    "Session expired. Refresh the Steam Account session from Session before buying.",
                    "warning",
                )
            return False

        self.add_event("Session expired. Attempting Pearl Abyss Account browser re-authentication.", "warning")
        if await self.refresh_pa_browser_session():
            self.add_event("Session expired. Re-authentication successful.", "success")
            return True

        self._set_saved_session_last_known_valid(False)
        self.pause_buy_mode_for_session_refresh("Session expired. Pearl Abyss Account refresh required.")
        self.add_event("Session expired. Re-authentication failed.", "error")
        return False
