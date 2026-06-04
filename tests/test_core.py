import asyncio
import json
import requests
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import main as app_main
from rich.console import Console
from textual.color import Color
from textual.widgets import Button, Input, Select, Static
from bdo_marketplace_tools.market.api_handler import (
    APIHandler,
    DEFAULT_PURCHASE_DELAY_BOUNDS,
    MARKET_AJAX_HEADER,
    MarketplaceAPIError,
    MarketplaceResponseError,
    marketplace_silver_balance,
    purchase_result_message,
)
from bdo_marketplace_tools.market.browser_auth import (
    BrowserAuthError,
    COOKIE_CONSENT_MANUAL,
    COOKIE_CONSENT_NOT_FOUND,
    COOKIE_CONSENT_SAVED,
    STEAM_AUTO_LOGIN_CLICKED,
    STEAM_AUTO_LOGIN_DISABLED,
    STEAM_AUTO_LOGIN_MANUAL_NEEDED,
    STEAM_AUTO_LOGIN_SKIPPED,
    STEAM_BROWSER_CHANNEL,
    STEAM_MARKET_DIAGNOSTIC_PROFILE_PATH,
    STEAM_MARKET_PROFILE_PATH,
    _accept_required_cookie_consent_if_available,
    _browser_launch_error_message,
    _classify_url,
    _market_cookie_capture_ready,
    _maybe_run_steam_auto_login,
    _new_steam_auto_login_state,
    _should_attempt_steam_auto_login,
    _status_for_state,
)
from bdo_marketplace_tools.market.pricing import (
    CLASSIC_OUTFIT_MAX_PRICE,
    OUTFIT_SET_MAX_PRICE,
    PREMIUM_OUTFIT_MAX_PRICE,
    apply_price_rules,
    purchase_record_count,
    purchase_record_spend,
)
from bdo_marketplace_tools.market.test_mode import SINGLE_ITEM_TEST_TARGET, check_single_item_stock, parse_single_item_stock_response
from bdo_marketplace_tools.storage import app_settings as account_mode_module
from bdo_marketplace_tools.storage import credentials as credentials_module
from bdo_marketplace_tools.services import task_manager as task_manager_module
from bdo_marketplace_tools.storage.app_settings import PA_CREDENTIALS_MODE, STEAM_BROWSER_MODE
from bdo_marketplace_tools.services.task_manager import BackgroundTasks
from bdo_marketplace_tools.ui.app import BANNER_ART, DEFAULT_THEME, STATUS_STYLES, DashboardTile, MarketplaceToolsApp, ModalAction
from bdo_marketplace_tools.version import APP_CHANNEL, APP_VERSION, PROJECT_NAME, SETTINGS_SCHEMA_VERSION


LOCAL_DATA = {
    "successful_purchases": 0,
    "silver_spent": 0,
}

EXPECTED_APP_SETTINGS_VERSION = {
    "schema": SETTINGS_SCHEMA_VERSION,
    "app": APP_VERSION,
    "channel": APP_CHANNEL,
    "project": PROJECT_NAME,
}


class FakeAPI:
    login_status = False
    email = None
    password = None
    account_mode = PA_CREDENTIALS_MODE
    session_cleared = False

    async def get_mp_inventory(self):
        return {
            "myWalletList": [
                {"mainKey": 1, "subKey": 0, "name": "Silver", "count": "123456789"},
            ],
            "useValuePackage": True,
            "totalWeight": 12,
            "maxWeight": 100,
        }

    async def check_stock(self):
        return []

    async def is_session_expired(self):
        return 0 if self.login_status else -1

    async def login(self):
        self.login_status = True
        return 1

    def save_session(self):
        pass

    def has_session_cookies(self):
        return bool(getattr(self, "session_has_cookies", self.login_status))

    def clear_session(self, save=True):
        self.login_status = False
        self.session_cleared = True


class FakeApp:
    instances = []

    def __init__(self, task_manager, api_handler, launch_mode="live"):
        self.task_manager = task_manager
        self.api_handler = api_handler
        self.launch_mode = launch_mode
        self.run_async = AsyncMock()
        self.instances.append(self)


class LaunchModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_test_mode_skips_startup_session_check(self):
        fake_api = FakeAPI()
        with patch("bdo_marketplace_tools.services.task_manager._load_local_data", return_value=LOCAL_DATA.copy()):
            fake_manager = BackgroundTasks(fake_api, persist_ui_settings=False)
        fake_manager.initial_login_check = AsyncMock()
        FakeApp.instances = []

        with patch("main.APIHandler", return_value=fake_api), patch(
            "main.BackgroundTasks",
            return_value=fake_manager,
        ), patch("main.MarketplaceToolsApp", FakeApp):
            await app_main.run_app(test_mode=True)

        fake_manager.initial_login_check.assert_not_called()
        self.assertFalse(fake_api.login_status)
        self.assertEqual(FakeApp.instances[0].launch_mode, "test")
        self.assertTrue(any("Test mode active" in event for event in fake_manager.events))

    async def test_live_mode_runs_startup_session_check(self):
        fake_api = FakeAPI()
        with patch("bdo_marketplace_tools.services.task_manager._load_local_data", return_value=LOCAL_DATA.copy()):
            fake_manager = BackgroundTasks(fake_api, persist_ui_settings=False)
        fake_manager.initial_login_check = AsyncMock()
        FakeApp.instances = []

        with patch("main.APIHandler", return_value=fake_api), patch(
            "main.BackgroundTasks",
            return_value=fake_manager,
        ), patch("main.MarketplaceToolsApp", FakeApp):
            await app_main.run_app(test_mode=False)

        fake_manager.initial_login_check.assert_awaited_once()
        self.assertEqual(FakeApp.instances[0].launch_mode, "live")

    def test_env_var_enables_test_mode(self):
        with patch.dict("os.environ", {"BDO_MARKET_TEST_MODE": "true"}):
            self.assertTrue(app_main.env_test_mode())

        with patch.dict("os.environ", {"BDO_MARKET_TEST_MODE": "0"}):
            self.assertFalse(app_main.env_test_mode())


class PricingTests(unittest.TestCase):
    def test_apply_price_rules_uses_known_rules_and_reports_fallbacks(self):
        adjusted, fallbacks = apply_price_rules(
            [
                ["premium", "1", "2020000000"],
                ["classic", "1", "1630000000"],
                ["set", "1", "1100000000"],
                ["unknown", "2", "12345"],
            ]
        )

        self.assertEqual(
            adjusted,
            [
                ["premium", "1", PREMIUM_OUTFIT_MAX_PRICE],
                ["classic", "1", CLASSIC_OUTFIT_MAX_PRICE],
                ["set", "1", OUTFIT_SET_MAX_PRICE],
                ["unknown", "2", OUTFIT_SET_MAX_PRICE],
            ],
        )
        self.assertEqual(
            fallbacks,
            [{"item_id": "unknown", "detected_price": "12345", "adjusted_price": OUTFIT_SET_MAX_PRICE}],
        )

    def test_purchase_record_helpers_sum_actual_successes(self):
        records = [
            {"item_id": "a", "price": 100, "count": 2},
            {"item_id": "b", "price": 250, "count": 1},
        ]

        self.assertEqual(purchase_record_count(records), 3)
        self.assertEqual(purchase_record_spend(records), 450)


class APIResultTests(unittest.TestCase):
    def test_browser_auth_launch_error_names_missing_patchright_browser_install(self):
        message = _browser_launch_error_message(
            RuntimeError("Executable doesn't exist at C:/ms-playwright/chromium/chrome.exe")
        )

        self.assertIn("Patchright Chromium is not installed", message)
        self.assertIn("py -m patchright install chromium", message)

    def test_browser_auth_uses_installed_chrome_channel(self):
        self.assertEqual(STEAM_BROWSER_CHANNEL, "chrome")

    def test_cookiebot_required_consent_click_is_best_effort(self):
        clicked_selectors = []
        statuses = []
        wait_calls = []

        class FakeFirstLocator:
            def __init__(self, selector):
                self.selector = selector

            async def click(self, timeout=None):
                if self.selector != "#CybotCookiebotDialogBodyButtonDecline":
                    raise RuntimeError("not found")
                clicked_selectors.append((self.selector, timeout))

        class FakeLocator:
            def __init__(self, selector):
                self.first = FakeFirstLocator(selector)
                self.selector = selector

            async def wait_for(self, state=None, timeout=None):
                wait_calls.append((self.selector, state, timeout))

        class FakePage:
            def locator(self, selector):
                return FakeLocator(selector)

        async def status_callback(message, level):
            statuses.append((message, level))

        self.assertEqual(
            asyncio.run(_accept_required_cookie_consent_if_available(FakePage(), status_callback=status_callback)),
            COOKIE_CONSENT_SAVED,
        )
        self.assertEqual(clicked_selectors, [("#CybotCookiebotDialogBodyButtonDecline", 8000)])
        self.assertEqual(wait_calls, [("#CybotCookiebotDialog", "hidden", 3000)])
        self.assertEqual(statuses, [("Required cookie consent saved in the Steam browser profile.", "info")])

    def test_cookiebot_required_consent_reports_click_when_dialog_remains(self):
        statuses = []

        class FakeFirstLocator:
            async def click(self, timeout=None):
                return None

        class FakeLocator:
            first = FakeFirstLocator()

            async def wait_for(self, state=None, timeout=None):
                raise RuntimeError("dialog still visible")

        class FakePage:
            def locator(self, selector):
                return FakeLocator()

        async def status_callback(message, level):
            statuses.append((message, level))

        self.assertEqual(
            asyncio.run(_accept_required_cookie_consent_if_available(FakePage(), status_callback=status_callback)),
            COOKIE_CONSENT_MANUAL,
        )
        self.assertEqual(
            statuses,
            [("Required cookie consent click sent; continue manually if the banner remains.", "info")],
        )

    def test_cookiebot_required_consent_returns_not_found_silently(self):
        statuses = []

        class FakeFirstLocator:
            async def click(self, timeout=None):
                raise RuntimeError("not found")

        class FakeLocator:
            first = FakeFirstLocator()

        class FakePage:
            def locator(self, selector):
                return FakeLocator()

        async def status_callback(message, level):
            statuses.append((message, level))

        self.assertEqual(
            asyncio.run(_accept_required_cookie_consent_if_available(FakePage(), status_callback=status_callback)),
            COOKIE_CONSENT_NOT_FOUND,
        )
        self.assertEqual(statuses, [])

    def test_steam_auto_login_disabled_does_not_click_buttons(self):
        clicked_selectors = []
        statuses = []

        class FakeFirstLocator:
            def __init__(self, selector):
                self.selector = selector

            async def click(self, timeout=None):
                clicked_selectors.append((self.selector, timeout))

        class FakeLocator:
            def __init__(self, selector):
                self.first = FakeFirstLocator(selector)

        class FakePage:
            url = "https://account.pearlabyss.com/en-us/Member/Login"

            def locator(self, selector):
                return FakeLocator(selector)

        async def status_callback(message, level):
            statuses.append((message, level))

        result = asyncio.run(
            _maybe_run_steam_auto_login(
                FakePage(),
                "pa",
                enabled=False,
                tracking=_new_steam_auto_login_state(),
                status_callback=status_callback,
            )
        )

        self.assertEqual(result, STEAM_AUTO_LOGIN_DISABLED)
        self.assertEqual(clicked_selectors, [])
        self.assertEqual(statuses, [])

    def test_steam_auto_login_clicks_pa_steam_button(self):
        clicked_selectors = []
        statuses = []

        class FakeFirstLocator:
            def __init__(self, selector):
                self.selector = selector

            async def click(self, timeout=None):
                if self.selector != "#btnSteam":
                    raise RuntimeError("not found")
                clicked_selectors.append((self.selector, timeout))

        class FakeLocator:
            def __init__(self, selector):
                self.first = FakeFirstLocator(selector)

        class FakePage:
            url = "https://account.pearlabyss.com/en-us/Member/Login"

            def locator(self, selector):
                return FakeLocator(selector)

        async def status_callback(message, level):
            statuses.append((message, level))

        result = asyncio.run(
            _maybe_run_steam_auto_login(
                FakePage(),
                "pa",
                enabled=True,
                tracking=_new_steam_auto_login_state(),
                status_callback=status_callback,
            )
        )

        self.assertEqual(result, STEAM_AUTO_LOGIN_CLICKED)
        self.assertEqual(clicked_selectors, [("#btnSteam", 1000)])
        self.assertEqual(statuses, [("Automatic Steam re-auth clicked Log in with Steam.", "info")])

    def test_steam_auto_login_clicks_pa_steam_button_inside_frame(self):
        clicked_selectors = []
        statuses = []

        class MissingFirstLocator:
            async def click(self, timeout=None):
                raise RuntimeError("not found")

        class MissingLocator:
            first = MissingFirstLocator()

        class FrameFirstLocator:
            def __init__(self, selector):
                self.selector = selector

            async def click(self, timeout=None):
                if self.selector != "#btnSteam":
                    raise RuntimeError("not found")
                clicked_selectors.append((self.selector, timeout))

        class FrameLocator:
            def __init__(self, selector):
                self.first = FrameFirstLocator(selector)

        class FakeFrame:
            url = "https://account.pearlabyss.com/en-us/Member/Login"

            def locator(self, selector):
                return FrameLocator(selector)

        class FakePage:
            url = "https://na-trade.naeu.playblackdesert.com/"
            frames = [FakeFrame()]

            def locator(self, selector):
                return MissingLocator()

        async def status_callback(message, level):
            statuses.append((message, level))

        result = asyncio.run(
            _maybe_run_steam_auto_login(
                FakePage(),
                "market",
                enabled=True,
                tracking=_new_steam_auto_login_state(),
                status_callback=status_callback,
            )
        )

        self.assertEqual(result, STEAM_AUTO_LOGIN_CLICKED)
        self.assertEqual(clicked_selectors, [("#btnSteam", 1000)])
        self.assertEqual(statuses, [("Automatic Steam re-auth clicked Log in with Steam.", "info")])

    def test_steam_auto_login_does_not_probe_top_level_market_page_for_pa_button(self):
        clicked_selectors = []

        class FakeFirstLocator:
            def __init__(self, selector):
                self.selector = selector

            async def click(self, timeout=None):
                clicked_selectors.append((self.selector, timeout))

        class FakeLocator:
            def __init__(self, selector):
                self.first = FakeFirstLocator(selector)

        class FakePage:
            url = "https://na-trade.naeu.playblackdesert.com/"
            frames = []

            def locator(self, selector):
                return FakeLocator(selector)

        result = asyncio.run(
            _maybe_run_steam_auto_login(
                FakePage(),
                "market",
                enabled=True,
                tracking=_new_steam_auto_login_state(),
            )
        )

        self.assertEqual(result, STEAM_AUTO_LOGIN_SKIPPED)
        self.assertEqual(clicked_selectors, [])

    def test_steam_auto_login_clicks_steam_sign_in_button(self):
        clicked_selectors = []
        statuses = []

        class FakeFirstLocator:
            def __init__(self, selector):
                self.selector = selector

            async def click(self, timeout=None):
                if self.selector != "#imageLogin":
                    raise RuntimeError("not found")
                clicked_selectors.append((self.selector, timeout))

        class FakeLocator:
            def __init__(self, selector):
                self.first = FakeFirstLocator(selector)

        class FakePage:
            url = "https://steamcommunity.com/openid/login"

            def locator(self, selector):
                return FakeLocator(selector)

        async def status_callback(message, level):
            statuses.append((message, level))

        result = asyncio.run(
            _maybe_run_steam_auto_login(
                FakePage(),
                "steam",
                enabled=True,
                tracking=_new_steam_auto_login_state(),
                status_callback=status_callback,
            )
        )

        self.assertEqual(result, STEAM_AUTO_LOGIN_CLICKED)
        self.assertEqual(clicked_selectors, [("#imageLogin", 1000)])
        self.assertEqual(statuses, [("Automatic Steam re-auth clicked Steam Sign In.", "info")])

    def test_steam_auto_login_leaves_otp_status_only(self):
        clicked_selectors = []
        statuses = []
        state, _is_callback = _classify_url("https://account.pearlabyss.com/en-us/Member/Login/CheckOtp")

        class FakeFirstLocator:
            def __init__(self, selector):
                self.selector = selector

            async def click(self, timeout=None):
                clicked_selectors.append((self.selector, timeout))

        class FakeLocator:
            def __init__(self, selector):
                self.first = FakeFirstLocator(selector)

        class FakePage:
            url = "https://account.pearlabyss.com/en-us/Member/Login/CheckOtp"

            def locator(self, selector):
                return FakeLocator(selector)

        async def status_callback(message, level):
            statuses.append((message, level))

        result = asyncio.run(
            _maybe_run_steam_auto_login(
                FakePage(),
                state,
                enabled=True,
                tracking=_new_steam_auto_login_state(),
                status_callback=status_callback,
            )
        )

        self.assertEqual(state, "otp")
        self.assertEqual(_status_for_state(state), ("OTP required. Complete verification in the browser.", "warning"))
        self.assertEqual(result, STEAM_AUTO_LOGIN_SKIPPED)
        self.assertEqual(clicked_selectors, [])
        self.assertEqual(statuses, [])

    def test_steam_auto_login_missing_button_reports_manual_input_without_failing(self):
        statuses = []

        class FakeFirstLocator:
            async def click(self, timeout=None):
                raise RuntimeError("not found")

        class FakeLocator:
            first = FakeFirstLocator()

        class FakePage:
            url = "https://account.pearlabyss.com/en-us/Member/Login"

            def locator(self, selector):
                return FakeLocator()

        async def status_callback(message, level):
            statuses.append((message, level))

        result = asyncio.run(
            _maybe_run_steam_auto_login(
                FakePage(),
                "pa",
                enabled=True,
                tracking=_new_steam_auto_login_state(),
                status_callback=status_callback,
                now=10,
                missing_notice_seconds=0,
            )
        )

        self.assertEqual(result, STEAM_AUTO_LOGIN_MANUAL_NEEDED)
        self.assertEqual(
            statuses,
            [("Automatic Steam re-auth is waiting for manual input on the Pearl Abyss page.", "warning")],
        )

    def test_steam_auto_login_skips_market_page_after_auth_flow_seen(self):
        self.assertTrue(_should_attempt_steam_auto_login("market", False, False))
        self.assertFalse(_should_attempt_steam_auto_login("market", True, False))
        self.assertFalse(_should_attempt_steam_auto_login("market", False, True))
        self.assertTrue(_should_attempt_steam_auto_login("pa", True, False))

    def test_market_cookie_capture_allows_fast_auto_redirect_after_auth_flow(self):
        cookies = [{"name": "anonymous-looking-cookie", "value": "ok"}]

        self.assertFalse(_market_cookie_capture_ready(cookies, False, True, False))
        self.assertTrue(_market_cookie_capture_ready(cookies, False, True, True))
        self.assertTrue(_market_cookie_capture_ready(cookies, True, False, False))
        self.assertFalse(_market_cookie_capture_ready(cookies, False, False, True))

    def test_browser_auth_launch_error_names_missing_google_chrome(self):
        message = _browser_launch_error_message(
            RuntimeError("Executable doesn't exist at C:/Program Files/Google/Chrome/Application/chrome.exe")
        )

        self.assertIn("Google Chrome is not available", message)

    def test_purchase_result_messages_name_known_codes(self):
        self.assertIn("identical order already exists", purchase_result_message(30, "item", "100"))
        self.assertIn("price mismatch", purchase_result_message(-14, "item", "100"))
        self.assertIn("duplicate pre-order", purchase_result_message(34, "item", "100"))
        self.assertIn("resultCode 999", purchase_result_message(999, "item", "100"))

    def test_purchase_result_code_validation(self):
        handler = object.__new__(APIHandler)

        self.assertEqual(APIHandler._purchase_result_code(handler, {"resultCode": "-14"}), -14)
        with self.assertRaises(MarketplaceResponseError):
            APIHandler._purchase_result_code(handler, {})

    def test_missing_session_file_is_initialized_with_empty_cookie_store(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session_path = Path(temp_dir) / "data" / "session.json"
            handler = object.__new__(APIHandler)

            with patch("bdo_marketplace_tools.market.api_handler.SESSION_COOKIE_PATH", session_path):
                status = APIHandler.load_session(handler)

            self.assertEqual(status, -1)
            self.assertTrue(session_path.exists())
            self.assertEqual(json.loads(session_path.read_text(encoding="utf-8")), {"version": 1, "cookies": []})

    def test_market_ajax_headers_keep_browser_like_shape_without_client_hints(self):
        handler = object.__new__(APIHandler)

        headers = APIHandler._market_headers(
            handler,
            "https://na-trade.naeu.playblackdesert.com/Home/list/hot",
            ajax=True,
        )

        self.assertEqual(headers["Origin"], "https://na-trade.naeu.playblackdesert.com")
        self.assertEqual(headers["Referer"], "https://na-trade.naeu.playblackdesert.com/Home/list/hot")
        self.assertEqual(headers["X-Requested-With"], MARKET_AJAX_HEADER)
        self.assertIn("Chrome/", headers["User-Agent"])
        self.assertNotIn("Sec-Fetch-Site", headers)
        self.assertNotIn("Sec-CH-UA", headers)

    def test_marketplace_silver_balance_reads_silver_wallet_row(self):
        wallet = {
            "myWalletList": [
                {"mainKey": 2, "subKey": 0, "name": "Other", "count": 5},
                {"mainKey": 1, "subKey": 0, "name": "Silver", "count": "123456789"},
            ]
        }

        self.assertEqual(marketplace_silver_balance(wallet), 123_456_789)
        self.assertIsNone(marketplace_silver_balance({"myWalletList": []}))
        with self.assertRaises(MarketplaceResponseError):
            marketplace_silver_balance({"myWalletList": [{"mainKey": 1, "subKey": 0, "name": "Silver"}]})


class LocalRuntimeFileTests(unittest.TestCase):
    def test_missing_account_mode_settings_defaults_to_pa_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            settings_path = temp_path / "data" / "app_settings.json"

            with patch("bdo_marketplace_tools.storage.app_settings.APP_SETTINGS_PATH", settings_path):
                self.assertEqual(account_mode_module.load_account_mode(), PA_CREDENTIALS_MODE)
                self.assertFalse(account_mode_module.load_steam_browser_profile_prepared())
                self.assertEqual(account_mode_module.save_account_mode(STEAM_BROWSER_MODE), STEAM_BROWSER_MODE)
                self.assertTrue(account_mode_module.save_steam_browser_profile_prepared(True))
                self.assertEqual(account_mode_module.load_account_mode(), STEAM_BROWSER_MODE)
                self.assertTrue(account_mode_module.load_steam_browser_profile_prepared())
                self.assertEqual(account_mode_module.account_mode_label(STEAM_BROWSER_MODE), "Steam Account")
                self.assertEqual(account_mode_module.account_mode_label(PA_CREDENTIALS_MODE), "Pearl Abyss Account")
                self.assertEqual(account_mode_module.normalize_account_mode("Steam Account"), STEAM_BROWSER_MODE)
                self.assertEqual(
                    account_mode_module.normalize_account_mode("Pearl Abyss Account"),
                    PA_CREDENTIALS_MODE,
                )

            self.assertTrue(settings_path.exists())
            saved_settings = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_settings["version"], EXPECTED_APP_SETTINGS_VERSION)
            self.assertEqual(saved_settings["account"]["mode"], STEAM_BROWSER_MODE)
            self.assertIsNone(saved_settings["account"]["email"])
            self.assertTrue(saved_settings["steam_browser"]["profile_prepared"])
            self.assertFalse(saved_settings["session"]["saved_session_last_known_valid"])
            self.assertEqual(saved_settings["ui"]["polling"]["selected"], "3")
            self.assertEqual(saved_settings["ui"]["polling"]["custom_range"], [15, 30])
            self.assertEqual(saved_settings["ui"]["buy_delay"]["range"], [1.0, 2.5])
            self.assertIsNone(saved_settings["ui"]["spend_cap"])
            self.assertFalse(saved_settings["ui"]["buy_mode"])
            self.assertEqual(saved_settings["ui"]["event_log_view"], "core")

    def test_app_settings_persist_ui_preferences(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            settings_path = temp_path / "data" / "app_settings.json"

            with patch("bdo_marketplace_tools.storage.app_settings.APP_SETTINGS_PATH", settings_path):
                account_mode_module.save_polling_settings("custom", (8, 13))
                account_mode_module.save_purchase_delay_bounds((4.5, 8))
                account_mode_module.save_spend_cap(123456789)
                account_mode_module.save_buy_mode(True)
                account_mode_module.save_event_log_view("ui")
                account_mode_module.save_saved_session_last_known_valid(True)
                settings = account_mode_module.read_app_settings()

            self.assertEqual(settings["ui"]["polling"]["selected"], "custom")
            self.assertEqual(settings["ui"]["polling"]["custom_range"], [8, 13])
            self.assertEqual(settings["ui"]["buy_delay"]["range"], [4.5, 8.0])
            self.assertEqual(settings["ui"]["spend_cap"], 123456789)
            self.assertTrue(settings["ui"]["buy_mode"])
            self.assertEqual(settings["ui"]["event_log_view"], "ui")
            self.assertTrue(settings["session"]["saved_session_last_known_valid"])
            with patch("bdo_marketplace_tools.storage.app_settings.APP_SETTINGS_PATH", settings_path):
                self.assertFalse(account_mode_module.save_saved_session_last_known_valid(False))
                self.assertFalse(account_mode_module.load_saved_session_last_known_valid())
                self.assertEqual(account_mode_module.save_event_log_view("bad-view"), "core")

    def test_background_tasks_load_and_save_persisted_ui_preferences(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            settings_path = temp_path / "data" / "app_settings.json"

            with patch("bdo_marketplace_tools.storage.app_settings.APP_SETTINGS_PATH", settings_path):
                account_mode_module.save_polling_settings("custom", (8, 13))
                account_mode_module.save_purchase_delay_bounds((4.5, 8))
                account_mode_module.save_spend_cap(250)
                account_mode_module.save_buy_mode(True)
                account_mode_module.save_event_log_view("ui")

                with patch("bdo_marketplace_tools.services.task_manager._load_local_data", return_value=LOCAL_DATA.copy()):
                    manager = BackgroundTasks(FakeAPI())

                self.assertEqual(manager.delay, "custom")
                self.assertEqual(manager.current_delay_bounds(), (8, 13))
                self.assertEqual(manager.purchase_delay_bounds, (4.5, 8.0))
                self.assertEqual(manager.max_spend, 250)
                self.assertTrue(manager.purchase_submission_enabled)
                self.assertEqual(manager.event_log_view, "ui")

                manager.set_delay_choice("2")
                manager.set_purchase_delay_range("1.25", "3.5")
                manager.set_spend_cap(0)
                manager.set_purchase_submission_enabled(False)
                manager.set_event_log_view("core")

                with patch("bdo_marketplace_tools.services.task_manager._load_local_data", return_value=LOCAL_DATA.copy()):
                    restored = BackgroundTasks(FakeAPI())

            self.assertEqual(restored.delay, "2")
            self.assertEqual(restored.current_delay_bounds(), (5, 10))
            self.assertEqual(restored.purchase_delay_bounds, (1.25, 3.5))
            self.assertIsNone(restored.max_spend)
            self.assertFalse(restored.purchase_submission_enabled)
            self.assertEqual(restored.event_log_view, "core")

    def test_old_resource_settings_are_ignored_for_fresh_start(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            settings_path = temp_path / "data" / "app_settings.json"
            old_settings_path = temp_path / "resources" / "app_settings.json"
            old_info_path = temp_path / "resources" / "info.json"
            old_settings_path.parent.mkdir(parents=True)
            old_settings_path.write_text(
                json.dumps(
                    {
                        "account_mode": STEAM_BROWSER_MODE,
                        "steam_browser_profile_prepared": True,
                    }
                ),
                encoding="utf-8",
            )
            old_info_path.write_text(
                json.dumps({"email": "user@example.com", "password": "old-secret"}),
                encoding="utf-8",
            )

            with patch("bdo_marketplace_tools.storage.app_settings.APP_SETTINGS_PATH", settings_path):
                settings = account_mode_module.read_app_settings()

            self.assertEqual(settings["account"]["mode"], PA_CREDENTIALS_MODE)
            self.assertIsNone(settings["account"]["email"])
            self.assertFalse(settings["steam_browser"]["profile_prepared"])
            saved_settings = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_settings, settings)

    def test_app_settings_refresh_version_metadata_when_read(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            settings_path = temp_path / "data" / "app_settings.json"
            settings_path.parent.mkdir(parents=True)
            settings_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "account": {"mode": STEAM_BROWSER_MODE, "email": "user@example.com"},
                        "steam_browser": {"profile_prepared": True},
                    }
                ),
                encoding="utf-8",
            )

            with patch("bdo_marketplace_tools.storage.app_settings.APP_SETTINGS_PATH", settings_path):
                settings = account_mode_module.read_app_settings()

            self.assertEqual(settings["version"], EXPECTED_APP_SETTINGS_VERSION)
            self.assertEqual(settings["account"]["mode"], STEAM_BROWSER_MODE)
            self.assertEqual(settings["account"]["email"], "user@example.com")
            saved_settings = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_settings["version"], EXPECTED_APP_SETTINGS_VERSION)

    def test_api_handler_initializes_account_mode_from_saved_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            settings_path = temp_path / "data" / "app_settings.json"
            session_path = temp_path / "data" / "session.json"

            with patch("bdo_marketplace_tools.storage.app_settings.APP_SETTINGS_PATH", settings_path):
                account_mode_module.save_account_mode(STEAM_BROWSER_MODE)
                with patch("bdo_marketplace_tools.market.api_handler.SESSION_COOKIE_PATH", session_path):
                    handler = APIHandler()

            self.assertEqual(handler.account_mode, STEAM_BROWSER_MODE)

    def test_missing_app_settings_credentials_are_initialized_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            settings_path = temp_path / "data" / "app_settings.json"

            with patch("bdo_marketplace_tools.storage.app_settings.APP_SETTINGS_PATH", settings_path):
                self.assertEqual(credentials_module.load_credentials(), (None, None))

            self.assertTrue(settings_path.exists())
            saved_settings = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertIsNone(saved_settings["account"]["email"])

    def test_credentials_use_project_keyring_namespace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            settings_path = temp_path / "data" / "app_settings.json"
            keyring_mock = Mock()
            keyring_mock.get_password.return_value = "saved-secret"

            with patch("bdo_marketplace_tools.storage.app_settings.APP_SETTINGS_PATH", settings_path), patch.object(
                credentials_module, "keyring", keyring_mock
            ):
                credentials_module.save_credentials("user@example.com", "new-secret")
                self.assertEqual(credentials_module.load_credentials(), ("user@example.com", "saved-secret"))

            keyring_mock.set_password.assert_called_once_with(
                "bdo-marketplace-tools", "user@example.com", "new-secret"
            )
            keyring_mock.get_password.assert_called_once_with("bdo-marketplace-tools", "user@example.com")
            saved_settings = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_settings["account"]["email"], "user@example.com")
            self.assertNotIn("new-secret", json.dumps(saved_settings))

    def test_missing_local_stats_file_is_initialized_with_default_totals(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_data_path = Path(temp_dir) / "data" / "local_stats.json"

            with patch("bdo_marketplace_tools.services.task_manager.LOCAL_DATA_PATH", local_data_path):
                data = task_manager_module._load_local_data()

            self.assertEqual(data, LOCAL_DATA)
            self.assertTrue(local_data_path.exists())
            payload = json.loads(local_data_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, LOCAL_DATA)
            self.assertNotIn("updated_at", payload)

    def test_old_local_data_file_is_ignored_for_fresh_start(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            local_stats_path = temp_path / "data" / "local_stats.json"
            old_local_data_path = temp_path / "resources" / "local_data.json"
            old_local_data_path.parent.mkdir(parents=True)
            old_local_data_path.write_text(
                json.dumps({"successful_purchases": 7, "silver_spent": 12345}),
                encoding="utf-8",
            )

            data = task_manager_module.load_local_stats(path=local_stats_path)

            self.assertEqual(data, LOCAL_DATA)
            self.assertTrue(local_stats_path.exists())
            self.assertEqual(json.loads(local_stats_path.read_text(encoding="utf-8")), LOCAL_DATA)

    def test_old_session_file_is_ignored_for_fresh_start(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            session_path = temp_path / "data" / "session.json"
            old_session_path = temp_path / "resources" / "session.json"
            old_session_path.parent.mkdir(parents=True)
            old_session_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "cookies": [
                            {
                                "name": "TradeAuth_Session",
                                "value": "abc123",
                                "domain": "na-trade.naeu.playblackdesert.com",
                                "path": "/",
                                "secure": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            handler = object.__new__(APIHandler)

            with patch("bdo_marketplace_tools.market.api_handler.SESSION_COOKIE_PATH", session_path):
                status = APIHandler.load_session(handler)

            self.assertEqual(status, -1)
            self.assertIsNone(handler.session.cookies.get("TradeAuth_Session"))
            self.assertTrue(session_path.exists())
            self.assertEqual(json.loads(session_path.read_text(encoding="utf-8")), {"version": 1, "cookies": []})

    def test_browser_profile_paths_use_data_directory(self):
        self.assertIn("data", STEAM_MARKET_PROFILE_PATH.parts)
        self.assertEqual(STEAM_MARKET_PROFILE_PATH.name, "steam-market")
        self.assertIn("data", STEAM_MARKET_DIAGNOSTIC_PROFILE_PATH.parts)
        self.assertEqual(STEAM_MARKET_DIAGNOSTIC_PROFILE_PATH.name, "steam-market-diagnostic")


class APIBuyFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_item_stock_check_uses_public_trademarket_sublist_endpoint(self):
        handler = object.__new__(APIHandler)
        captured = {}

        class StockResponse:
            status_code = 200
            url = "https://na-trade.naeu.playblackdesert.com/Trademarket/GetWorldMarketSubList"
            headers = {"Content-Type": "application/json; charset=utf-8"}

            def json(self):
                return {
                    "resultCode": 0,
                    "resultMsg": "10007-0-7-77000-6-479508-23100-82500-77000-1780084000|",
                }

        async def fake_request(client, method, url, context, **kwargs):
            captured.update({"client": client, "method": method, "url": url, "context": context, **kwargs})
            return StockResponse()

        handler._request = fake_request
        handler._json_response = APIHandler._json_response.__get__(handler, APIHandler)

        result = await check_single_item_stock(handler)

        self.assertEqual(result, [["10007", "6", "82500"]])
        self.assertIs(captured["client"], requests)
        self.assertEqual(captured["method"], "POST")
        self.assertTrue(captured["url"].endswith("/Trademarket/GetWorldMarketSubList"))
        self.assertEqual(captured["json"], {"keyType": 0, "mainKey": 10007})
        self.assertEqual(
            captured["headers"],
            {
                "Content-Type": "application/json",
                "User-Agent": "BlackDesert",
            },
        )
        self.assertNotIn("data", captured)

    async def test_single_item_stock_check_does_not_require_session_or_login_state(self):
        handler = object.__new__(APIHandler)

        class FakeResponse:
            status_code = 200
            url = "https://na-trade.naeu.playblackdesert.com/Trademarket/GetWorldMarketSubList"
            headers = {"Content-Type": "application/json; charset=utf-8"}

            def json(self):
                return {
                    "resultCode": 0,
                    "resultMsg": "10007-0-7-77000-1-479508-23100-82500-77000-1780084000|",
                }

        async def fake_request(*args, **kwargs):
            return FakeResponse()

        handler._request = fake_request
        handler._json_response = APIHandler._json_response.__get__(handler, APIHandler)

        result = await check_single_item_stock(handler)

        self.assertEqual(result, [["10007", "1", "82500"]])

    async def test_single_item_stock_check_rejects_public_endpoint_error_code(self):
        handler = object.__new__(APIHandler)

        class ErrorResponse:
            status_code = 200
            url = "https://na-trade.naeu.playblackdesert.com/Trademarket/GetWorldMarketSubList"
            headers = {"Content-Type": "application/json; charset=utf-8"}

            def json(self):
                return {"resultCode": -1, "resultMsg": "/Error"}

        async def fake_request(*args, **kwargs):
            return ErrorResponse()

        handler._request = fake_request
        handler._json_response = APIHandler._json_response.__get__(handler, APIHandler)

        with self.assertRaises(MarketplaceResponseError):
            await check_single_item_stock(handler)

    async def test_single_item_stock_response_returns_empty_when_target_row_has_no_stock(self):
        response_json = {
            "resultCode": 0,
            "resultMsg": "10007-0-7-77000-0-479508-23100-82500-77000-1780084000|",
        }

        result = parse_single_item_stock_response(
            response_json,
            SINGLE_ITEM_TEST_TARGET,
            "single-item test",
        )

        self.assertEqual(result, [])

    async def test_single_item_stock_response_matches_target_enhancement_range(self):
        response_json = {
            "resultCode": 0,
            "resultMsg": (
                "10007-8-10-1630000-3-754-500000-5000000-1720000-1777516443|"
                "10007-0-7-77000-2-479508-23100-82500-77000-1780084000|"
            ),
        }

        result = parse_single_item_stock_response(
            response_json,
            SINGLE_ITEM_TEST_TARGET,
            "single-item test",
        )

        self.assertEqual(result, [["10007", "2", "82500"]])

    async def test_single_item_stock_response_uses_configured_test_buy_price_not_public_prices(self):
        target = {
            **SINGLE_ITEM_TEST_TARGET,
            "max_buy_price": "82500",
        }
        response_json = {
            "resultCode": 0,
            "resultMsg": "10007-0-7-77000-1-479508-23100-99999-77000-1780084000|",
        }

        result = parse_single_item_stock_response(
            response_json,
            target,
            "single-item test",
        )

        self.assertEqual(result, [["10007", "1", "82500"]])

    async def test_single_item_stock_response_rejects_api_error_codes(self):
        with self.assertRaises(MarketplaceResponseError):
            parse_single_item_stock_response(
                {"resultCode": 2000, "resultMsg": "expired"},
                SINGLE_ITEM_TEST_TARGET,
                "single-item test",
            )

    async def test_buy_item_validates_session_before_purchase_requests(self):
        handler = object.__new__(APIHandler)
        calls = []

        async def invalid_session():
            calls.append("ensure_session_valid")
            return False

        handler.ensure_session_valid = invalid_session

        summary = await APIHandler.buy_item(handler, [["item", "1", "100"]])

        self.assertEqual(calls, ["ensure_session_valid"])
        self.assertEqual(summary["attempted"], 0)
        self.assertEqual(summary["purchased"], 0)
        self.assertEqual(summary["events"][0]["level"], "error")

    async def test_check_stock_uses_persistent_public_category_clients(self):
        handler = object.__new__(APIHandler)
        male_client = object()
        female_client = object()
        handler.public_market_sessions = {
            "male": male_client,
            "female": female_client,
        }
        captured_clients = []

        class FakeResponse:
            content = b"compressed"

        async def fake_request(client, *args, **kwargs):
            captured_clients.append(client)
            return FakeResponse()

        handler._request = fake_request
        handler._parse_world_market_response = lambda _content, context: [[context, "1", "100"]]

        result = await APIHandler.check_stock(handler)

        self.assertEqual(captured_clients, [male_client, female_client])
        self.assertEqual(
            result,
            [["male outfit stock", "1", "100"], ["female outfit stock", "1", "100"]],
        )

    async def test_buy_item_returns_structured_purchase_records(self):
        handler = object.__new__(APIHandler)
        session_requests = []

        async def valid_session():
            return True

        class FakeResponse:
            def json(self):
                return {"resultCode": 0}

        async def fake_session_request(*args, **kwargs):
            session_requests.append((args, kwargs))
            return FakeResponse()

        handler.ensure_session_valid = valid_session
        handler._session_request = fake_session_request
        handler._json_response = APIHandler._json_response.__get__(handler, APIHandler)
        handler._purchase_result_code = APIHandler._purchase_result_code.__get__(handler, APIHandler)

        sleep_mock = AsyncMock()
        with patch("bdo_marketplace_tools.market.api_handler.asyncio.sleep", new=sleep_mock):
            summary = await APIHandler.buy_item(handler, [["item", "2", "100"]])

        self.assertEqual(summary["attempted"], 2)
        self.assertEqual(summary["purchased"], 2)
        self.assertEqual(
            summary["purchase_records"],
            [
                {"item_id": "item", "price": 100, "submitted_price": 100, "count": 1, "result_code": 0},
                {"item_id": "item", "price": 100, "submitted_price": 100, "count": 1, "result_code": 0},
            ],
        )
        headers = session_requests[0][1]["headers"]
        self.assertEqual(headers["Origin"], "https://na-trade.naeu.playblackdesert.com")
        self.assertEqual(headers["Referer"], "https://na-trade.naeu.playblackdesert.com/")
        self.assertNotIn("X-Requested-With", headers)
        payload = session_requests[0][1]["data"]
        self.assertEqual(payload["buyMainKey"], "item")
        self.assertEqual(payload["buySubKey"], "0")
        self.assertEqual(payload["buyKeyType"], "0")
        self.assertEqual(payload["buyChooseKey"], "0")
        self.assertEqual(payload["buyPrice"], "100")
        self.assertEqual(payload["buyCount"], "1")
        self.assertEqual(sleep_mock.await_count, 1)

    async def test_buy_item_uses_configured_delay_between_purchase_attempts(self):
        handler = object.__new__(APIHandler)

        async def valid_session():
            return True

        class FakeResponse:
            def json(self):
                return {"resultCode": 0}

        async def fake_session_request(*args, **kwargs):
            return FakeResponse()

        handler.ensure_session_valid = valid_session
        handler._session_request = fake_session_request
        handler._json_response = APIHandler._json_response.__get__(handler, APIHandler)
        handler._purchase_result_code = APIHandler._purchase_result_code.__get__(handler, APIHandler)

        with patch("bdo_marketplace_tools.market.api_handler.random.uniform", return_value=4.5) as uniform_mock:
            with patch("bdo_marketplace_tools.market.api_handler.asyncio.sleep", new=AsyncMock()) as sleep_mock:
                summary = await APIHandler.buy_item(
                    handler,
                    [["item", "3", "100"]],
                    purchase_delay_bounds=(4, 7),
                )

        self.assertEqual(summary["attempted"], 3)
        self.assertEqual(summary["purchase_delay_bounds"], (4.0, 7.0))
        self.assertEqual(uniform_mock.call_count, 2)
        uniform_mock.assert_called_with(4.0, 7.0)
        self.assertEqual(sleep_mock.await_count, 2)
        sleep_mock.assert_awaited_with(4.5)

    async def test_buy_item_retries_same_item_once_after_session_expiry_result(self):
        handler = object.__new__(APIHandler)
        handler.login_status = True
        handler.session = type("Session", (), {"cookies": {"session": "present"}})()
        ensure_calls = 0
        session_payloads = []
        response_payloads = [
            {"resultCode": 2000},
            {"resultCode": 0, "resultMsg": "item-0-1-100-1-100-0-0-0-False"},
        ]

        async def valid_session():
            nonlocal ensure_calls
            ensure_calls += 1
            handler.login_status = True
            return True

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        async def fake_session_request(*args, **kwargs):
            session_payloads.append(kwargs["data"])
            return FakeResponse(response_payloads.pop(0))

        handler.ensure_session_valid = valid_session
        handler._session_request = fake_session_request
        handler._json_response = APIHandler._json_response.__get__(handler, APIHandler)
        handler._purchase_result_code = APIHandler._purchase_result_code.__get__(handler, APIHandler)
        handler._purchase_result_details = APIHandler._purchase_result_details.__get__(handler, APIHandler)
        handler._optional_positive_int = APIHandler._optional_positive_int.__get__(handler, APIHandler)

        summary = await APIHandler.buy_item(
            handler,
            [["item", "1", "100"]],
            purchase_delay_bounds=(0, 0),
        )

        self.assertEqual(ensure_calls, 1)
        self.assertEqual([payload["buyMainKey"] for payload in session_payloads], ["item", "item"])
        self.assertEqual(summary["attempted"], 2)
        self.assertEqual([record["result_code"] for record in summary["results"]], [2000, 0])
        self.assertEqual(summary["purchased"], 1)
        self.assertEqual(summary["purchase_records"][0]["item_id"], "item")

    async def test_buy_item_rejects_invalid_purchase_delay_bounds(self):
        handler = object.__new__(APIHandler)

        with self.assertRaises(MarketplaceResponseError):
            await APIHandler.buy_item(handler, [["item", "1", "100"]], purchase_delay_bounds=(5, 1))

    async def test_buy_item_uses_actual_purchase_price_from_result_message(self):
        handler = object.__new__(APIHandler)

        async def valid_session():
            return True

        class FakeResponse:
            def json(self):
                return {"resultCode": 0, "resultMsg": "10007-0-1-82500-1-79000-0-0-0-False"}

        async def fake_session_request(*args, **kwargs):
            return FakeResponse()

        handler.ensure_session_valid = valid_session
        handler._session_request = fake_session_request
        handler._json_response = APIHandler._json_response.__get__(handler, APIHandler)
        handler._purchase_result_code = APIHandler._purchase_result_code.__get__(handler, APIHandler)
        handler._purchase_result_details = APIHandler._purchase_result_details.__get__(handler, APIHandler)
        handler._optional_positive_int = APIHandler._optional_positive_int.__get__(handler, APIHandler)

        with patch("bdo_marketplace_tools.market.api_handler.asyncio.sleep", new=AsyncMock()):
            summary = await APIHandler.buy_item(handler, [["10007", "1", "82500"]])

        self.assertEqual(summary["purchased"], 1)
        self.assertEqual(
            summary["purchase_records"],
            [{"item_id": "10007", "price": 79000, "submitted_price": 82500, "count": 1, "result_code": 0}],
        )
        self.assertIn("79000 silver", summary["events"][0]["message"])
        self.assertIn("submitted up to 82500", summary["events"][0]["message"])

    async def test_buy_item_result_code_zero_preorder_does_not_count_as_purchase(self):
        handler = object.__new__(APIHandler)

        async def valid_session():
            return True

        class FakeResponse:
            def json(self):
                return {"resultCode": 0, "resultMsg": "10007-0-1-79000-0-79000-79000-92404197-0-False"}

        async def fake_session_request(*args, **kwargs):
            return FakeResponse()

        handler.ensure_session_valid = valid_session
        handler._session_request = fake_session_request
        handler._json_response = APIHandler._json_response.__get__(handler, APIHandler)
        handler._purchase_result_code = APIHandler._purchase_result_code.__get__(handler, APIHandler)
        handler._purchase_result_details = APIHandler._purchase_result_details.__get__(handler, APIHandler)
        handler._optional_positive_int = APIHandler._optional_positive_int.__get__(handler, APIHandler)

        summary = await APIHandler.buy_item(handler, [["10007", "1", "79000"]])

        self.assertEqual(summary["purchased"], 0)
        self.assertEqual(summary["purchase_records"], [])
        self.assertEqual(summary["results"][0]["outcome"], "preorder")
        self.assertEqual(summary["results"][0]["reservation_id"], 92404197)
        self.assertIn("pre-order", summary["events"][0]["message"])

    async def test_session_refresh_uses_browser_observed_ajax_body(self):
        handler = object.__new__(APIHandler)
        handler.session = type("Session", (), {"cookies": {"session": "present"}})()
        captured = {}

        class FakeResponse:
            def json(self):
                return {"_resultCode": 0}

        async def fake_session_request(method, url, context, **kwargs):
            captured.update({"method": method, "url": url, "context": context, **kwargs})
            return FakeResponse()

        handler._session_request = fake_session_request
        handler._json_response = APIHandler._json_response.__get__(handler, APIHandler)

        self.assertEqual(await APIHandler.is_session_expired(handler), 0)
        self.assertEqual(captured["data"], {"_isCalc": "false"})
        self.assertEqual(captured["headers"]["X-Requested-With"], MARKET_AJAX_HEADER)

    async def test_session_refresh_accepts_public_result_code_shape(self):
        handler = object.__new__(APIHandler)
        handler.session = type("Session", (), {"cookies": {"session": "present"}})()

        class FakeResponse:
            def json(self):
                return {"resultCode": 0, "resultMsg": ""}

        async def fake_session_request(*args, **kwargs):
            return FakeResponse()

        handler._session_request = fake_session_request
        handler._json_response = APIHandler._json_response.__get__(handler, APIHandler)

        self.assertEqual(await APIHandler.is_session_expired(handler), 0)

    async def test_browser_cookie_import_filters_market_domains_and_saves_after_validation(self):
        handler = object.__new__(APIHandler)
        handler.session = requests.Session()
        handler.login_status = False
        handler.is_session_expired = AsyncMock(return_value=0)
        handler.save_session = Mock()
        cookies = [
            {
                "name": "TradeAuth_Session",
                "value": "market-session",
                "domain": "na-trade.naeu.playblackdesert.com",
                "path": "/",
                "secure": True,
            },
            {
                "name": "steamLoginSecure",
                "value": "do-not-import",
                "domain": "steamcommunity.com",
                "path": "/",
                "secure": True,
            },
        ]

        self.assertTrue(await APIHandler.validate_and_save_imported_session(handler, cookies))

        saved_cookies = handler.session.cookies.get_dict(domain="na-trade.naeu.playblackdesert.com")
        self.assertEqual(saved_cookies, {"TradeAuth_Session": "market-session"})
        self.assertTrue(handler.login_status)
        handler.save_session.assert_called_once()

    async def test_failed_browser_cookie_validation_preserves_existing_session(self):
        handler = object.__new__(APIHandler)
        previous_session = requests.Session()
        previous_session.cookies.set("TradeAuth_Session", "old", domain="na-trade.naeu.playblackdesert.com", path="/")
        handler.session = previous_session
        handler.login_status = True
        handler.is_session_expired = AsyncMock(return_value=-1)
        handler.save_session = Mock()

        result = await APIHandler.validate_and_save_imported_session(
            handler,
            [
                {
                    "name": "TradeAuth_Session",
                    "value": "new",
                    "domain": "na-trade.naeu.playblackdesert.com",
                    "path": "/",
                }
            ],
        )

        self.assertFalse(result)
        self.assertIs(handler.session, previous_session)
        self.assertTrue(handler.login_status)
        handler.save_session.assert_not_called()

    async def test_steam_mode_session_validation_does_not_attempt_password_login(self):
        handler = object.__new__(APIHandler)
        handler.account_mode = STEAM_BROWSER_MODE
        handler.login_status = True
        handler.email = "user@example.com"
        handler.password = "secret"
        handler.is_session_expired = AsyncMock(return_value=-1)
        handler.login = AsyncMock(return_value=1)

        self.assertFalse(await APIHandler.ensure_session_valid(handler))
        handler.login.assert_not_called()
        self.assertFalse(handler.login_status)


class BackgroundTaskTests(unittest.IsolatedAsyncioTestCase):
    def make_task_manager(self, test_mode_enabled=False):
        with patch("bdo_marketplace_tools.services.task_manager._load_local_data", return_value=LOCAL_DATA.copy()), patch(
            "bdo_marketplace_tools.services.task_manager.load_account_mode",
            return_value=PA_CREDENTIALS_MODE,
        ), patch("bdo_marketplace_tools.services.task_manager.load_steam_browser_profile_prepared", return_value=True):
            return BackgroundTasks(FakeAPI(), test_mode_enabled=test_mode_enabled, persist_ui_settings=False)

    async def test_event_logs_split_core_and_ui_streams_while_preserving_combined_events(self):
        manager = self.make_task_manager()

        manager.add_event("Core monitor detail.", "success")
        manager.add_event("UI setting saved.", "info", channel="ui")

        self.assertTrue(any("Core monitor detail." in event for event in manager.events))
        self.assertTrue(any("UI setting saved." in event for event in manager.events))
        self.assertTrue(any("Core monitor detail." in event for event in manager.events_for_channel("core")))
        self.assertFalse(any("UI setting saved." in event for event in manager.events_for_channel("core")))
        self.assertTrue(any("UI setting saved." in event for event in manager.events_for_channel("ui")))
        self.assertFalse(any("Core monitor detail." in event for event in manager.events_for_channel("ui")))

    async def test_spend_cap_limits_items_by_price_order(self):
        manager = self.make_task_manager()
        manager.max_spend = 250

        capped = manager._apply_spend_cap([["a", "3", "100"], ["b", "2", "80"]])

        self.assertEqual(capped, [["a", "2", "100"]])

    async def test_spend_cap_applies_to_current_session_spend(self):
        manager = self.make_task_manager()
        manager.max_spend = 250
        manager.session_silver_spent = 100

        capped = manager._apply_spend_cap([["a", "3", "100"], ["b", "2", "80"]])

        self.assertEqual(capped, [["a", "1", "100"]])

        manager.session_silver_spent = 250
        self.assertEqual(manager._apply_spend_cap([["a", "1", "100"]]), [])

    async def test_login_status_checker_does_not_start_duplicates(self):
        manager = self.make_task_manager()

        async def idle_checker():
            await asyncio.sleep(60)

        manager.login_status_checker = idle_checker
        manager.start_login_status_checker()
        first_task = manager.login_checker_task
        manager.start_login_status_checker()

        self.assertIs(manager.login_checker_task, first_task)
        await manager.stop_login_status_checker()
        self.assertIsNone(manager.login_checker_task)

    async def test_monitor_start_and_stop_are_idempotent(self):
        manager = self.make_task_manager()

        async def idle_checker():
            await asyncio.sleep(60)

        manager.checker = idle_checker

        self.assertTrue(await manager.start_checker())
        first_task = manager.checker_task
        self.assertFalse(await manager.start_checker())
        self.assertIs(manager.checker_task, first_task)
        self.assertTrue(manager.checker_enabled)

        self.assertTrue(await manager.stop_checker())
        self.assertFalse(manager.checker_enabled)
        self.assertFalse(await manager.stop_checker())
        self.assertFalse(manager.checker_enabled)

    async def test_single_item_test_monitor_is_separate_and_idempotent(self):
        manager = self.make_task_manager(test_mode_enabled=True)

        async def idle_checker():
            await asyncio.sleep(60)

        manager.single_item_test_checker = idle_checker

        self.assertTrue(await manager.start_single_item_test_checker())
        first_task = manager.single_item_test_checker_task
        self.assertFalse(await manager.start_single_item_test_checker())
        self.assertIs(manager.single_item_test_checker_task, first_task)
        self.assertTrue(manager.single_item_test_checker_enabled)
        self.assertFalse(manager.single_item_test_purchase_enabled)
        self.assertFalse(manager.checker_enabled)
        self.assertFalse(await manager.start_checker())
        self.assertFalse(manager.checker_enabled)

        self.assertTrue(await manager.stop_single_item_test_checker())
        self.assertFalse(manager.single_item_test_checker_enabled)
        self.assertFalse(manager.single_item_test_purchase_enabled)
        self.assertFalse(await manager.stop_single_item_test_checker())

    async def test_test_mode_helpers_are_disabled_outside_test_mode(self):
        manager = self.make_task_manager()

        self.assertFalse(await manager.start_single_item_test_checker())
        self.assertIsNone(manager.single_item_test_checker_task)
        self.assertFalse(await manager.debug_fake_outfit_detection())
        self.assertFalse(await manager.debug_simulate_purchase_success())
        self.assertFalse(manager.set_simulated_session(True))
        self.assertFalse(manager.simulated_session_enabled)
        self.assertFalse(manager.api_handler.login_status)

    async def test_single_item_test_checker_processes_detection_without_live_buy(self):
        manager = self.make_task_manager(test_mode_enabled=True)
        manager.purchase_submission_enabled = True
        stock_check = AsyncMock(return_value=[["10007", "2", "82500"]])
        manager.api_handler.buy_item = AsyncMock()

        with patch("bdo_marketplace_tools.services.task_manager.check_single_item_stock", stock_check), patch(
            "bdo_marketplace_tools.services.task_manager.random.uniform",
            return_value=3,
        ), patch(
            "bdo_marketplace_tools.services.task_manager.asyncio.sleep",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await manager.single_item_test_checker()

        stock_check.assert_awaited_once_with(manager.api_handler, SINGLE_ITEM_TEST_TARGET)
        manager.api_handler.buy_item.assert_not_called()
        self.assertEqual(manager.session_detected_outfits, 2)
        self.assertEqual(manager.session_successful_purchases, 0)
        self.assertTrue(any("Test item detected: 2 available test items" in event for event in manager.events))

    async def test_single_item_test_checker_can_buy_without_outfit_price_adjustment(self):
        manager = self.make_task_manager(test_mode_enabled=True)
        stock_check = AsyncMock(return_value=[["10007", "2", "82500"]])
        manager.api_handler.buy_item = AsyncMock(
            return_value={
                "purchase_records": [
                    {
                        "item_id": "10007",
                        "price": 82500,
                        "count": 2,
                        "result_code": 0,
                    }
                ],
                "events": [{"level": "success", "message": "Test buy succeeded."}],
            }
        )
        manager.single_item_test_purchase_enabled = True

        with patch("bdo_marketplace_tools.services.task_manager.check_single_item_stock", stock_check), patch.object(
            manager,
            "save_local_data",
        ) as save_mock, patch(
            "bdo_marketplace_tools.services.task_manager.random.uniform",
            return_value=3,
        ), patch(
            "bdo_marketplace_tools.services.task_manager.asyncio.sleep",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await manager.single_item_test_checker()

        stock_check.assert_awaited_once_with(manager.api_handler, SINGLE_ITEM_TEST_TARGET)
        manager.api_handler.buy_item.assert_awaited_once_with(
            [["10007", "2", "82500"]],
            purchase_delay_bounds=DEFAULT_PURCHASE_DELAY_BOUNDS,
        )
        self.assertEqual(manager.session_detected_outfits, 2)
        self.assertEqual(manager.session_successful_purchases, 2)
        self.assertEqual(manager.session_silver_spent, 165000)
        self.assertFalse(any("Fallback pricing applied" in event for event in manager.events))
        save_mock.assert_called_once()

    async def test_buy_item_can_skip_outfit_price_rules_for_validated_rows(self):
        manager = self.make_task_manager()
        manager.api_handler.buy_item = AsyncMock(return_value={"purchase_records": [], "events": []})

        await manager.buy_item([["10007", 1, 82500]], adjust_pricing=False)

        manager.api_handler.buy_item.assert_awaited_once_with(
            [["10007", "1", "82500"]],
            purchase_delay_bounds=DEFAULT_PURCHASE_DELAY_BOUNDS,
        )
        self.assertFalse(any("Fallback pricing applied" in event for event in manager.events))

    async def test_purchase_delay_range_feeds_api_buy_delay(self):
        manager = self.make_task_manager()
        manager.api_handler.buy_item = AsyncMock(return_value={"purchase_records": [], "events": []})

        manager.set_purchase_delay_range("4.5", "8")
        await manager.buy_item([["10007", 1, 82500]], adjust_pricing=False)

        self.assertEqual(manager.purchase_delay_bounds, (4.5, 8.0))
        self.assertEqual(manager.purchase_delay_range(), "4.5-8s")
        manager.api_handler.buy_item.assert_awaited_once_with(
            [["10007", "1", "82500"]],
            purchase_delay_bounds=(4.5, 8.0),
        )

        with self.assertRaises(ValueError):
            manager.set_purchase_delay_range(10, 2)

    async def test_custom_delay_range_feeds_monitor_sleep_bounds(self):
        manager = self.make_task_manager()
        manager.set_custom_delay_range(8, 13)

        self.assertEqual(manager.delay, "custom")
        self.assertEqual(manager.current_delay_label(), "Custom")
        self.assertEqual(manager.current_delay_range(), "8-13s")
        self.assertEqual(manager.current_delay_bounds(), (8, 13))

        manager.set_custom_delay_range(5, 10)
        self.assertEqual(manager.delay, "2")
        self.assertEqual(manager.current_delay_label(), "Balanced")
        self.assertEqual(manager.current_delay_bounds(), (5, 10))

        manager.set_custom_delay_range(8, 13)
        manager.api_handler.check_stock = AsyncMock(return_value=[])
        with patch("bdo_marketplace_tools.services.task_manager.random.uniform", return_value=9) as uniform_mock:
            with patch("bdo_marketplace_tools.services.task_manager.asyncio.sleep", new=AsyncMock(side_effect=asyncio.CancelledError)):
                with self.assertRaises(asyncio.CancelledError):
                    await manager.checker()

        uniform_mock.assert_called_once_with(8, 13)

    async def test_monitor_errors_back_off_from_normal_polling_window(self):
        manager = self.make_task_manager()
        manager.set_custom_delay_range(5, 10)
        manager.consecutive_cycle_errors = 2

        with patch("bdo_marketplace_tools.services.task_manager.random.uniform", return_value=20) as uniform_mock:
            self.assertEqual(manager.next_sleep_duration(), 20)

        uniform_mock.assert_called_once_with(15, 30)

    async def test_fake_detection_uses_watch_only_path(self):
        manager = self.make_task_manager(test_mode_enabled=True)
        manager.purchase_submission_enabled = True
        manager.buy_item = AsyncMock()

        await manager.debug_fake_outfit_detection()

        manager.buy_item.assert_not_called()
        self.assertEqual(manager.session_detected_outfits, 1)
        self.assertEqual(manager.session_successful_purchases, 0)
        self.assertTrue(any("Outfit detected: 1" in event for event in manager.events))

    async def test_fake_purchase_updates_success_rate_and_local_totals(self):
        manager = self.make_task_manager(test_mode_enabled=True)
        with patch.object(manager, "save_local_data") as save_mock:
            await manager.debug_simulate_purchase_success()

        self.assertEqual(manager.session_detected_outfits, 1)
        self.assertEqual(manager.session_successful_purchases, 1)
        self.assertEqual(manager.lifetime_successful_purchases, 1)
        self.assertGreater(manager.session_silver_spent, 0)
        save_mock.assert_called_once()

    async def test_simulated_session_buy_mode_does_not_call_purchase_api(self):
        manager = self.make_task_manager(test_mode_enabled=True)
        manager.set_simulated_session(True)
        manager.purchase_submission_enabled = True
        manager.api_handler.buy_item = AsyncMock()

        with patch.object(manager, "save_local_data") as save_mock:
            await manager.process_detected_outfits([["debug-premium-outfit", "1", "2020000000"]])

        manager.api_handler.buy_item.assert_not_called()
        self.assertTrue(manager.api_handler.login_status)
        self.assertTrue(manager.simulated_session_enabled)
        self.assertEqual(manager.session_detected_outfits, 1)
        self.assertEqual(manager.session_successful_purchases, 1)
        self.assertGreater(manager.session_silver_spent, 0)
        self.assertTrue(any("Test-mode purchase simulated" in event for event in manager.events))
        save_mock.assert_called_once()

    async def test_disabling_simulated_session_returns_to_watch_only(self):
        manager = self.make_task_manager(test_mode_enabled=True)
        manager.set_simulated_session(True)
        manager.purchase_submission_enabled = True

        manager.set_simulated_session(False)

        self.assertFalse(manager.api_handler.login_status)
        self.assertFalse(manager.simulated_session_enabled)
        self.assertFalse(manager.purchase_submission_enabled)

    async def test_zero_purchase_summary_does_not_save_local_data(self):
        manager = self.make_task_manager()
        with patch.object(manager, "save_local_data") as save_mock:
            manager.record_purchase_summary(
                {
                    "purchase_records": [],
                    "events": [{"level": "warning", "message": "simulated no purchase"}],
                }
            )

        self.assertEqual(manager.session_successful_purchases, 0)
        self.assertEqual(manager.session_silver_spent, 0)
        save_mock.assert_not_called()

    async def test_zero_purchase_summary_does_not_add_generic_duplicate_when_reason_exists(self):
        manager = self.make_task_manager()

        manager.record_purchase_summary(
            {
                "purchase_records": [],
                "events": [{"level": "warning", "message": "Purchase failed: price mismatch."}],
            }
        )

        event_text = "\n".join(manager.events)
        self.assertIn("Purchase failed: price mismatch.", event_text)
        self.assertNotIn("Purchase attempt completed without a successful request.", event_text)

    async def test_monitor_cycle_errors_do_not_kill_checker_loop(self):
        manager = self.make_task_manager()
        manager.api_handler.check_stock = AsyncMock(return_value=[["bad-item", "not-a-number", "100"]])

        with patch("bdo_marketplace_tools.services.task_manager.asyncio.sleep", new=AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await manager.checker()

        self.assertTrue(any("Monitor cycle failed" in event for event in manager.events))

    async def test_checker_done_callback_marks_crashed_monitor_stopped(self):
        manager = self.make_task_manager()

        async def crash_checker():
            raise RuntimeError("simulated monitor crash")

        manager.checker = crash_checker
        await manager.start_checker()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        self.assertFalse(manager.checker_enabled)
        self.assertIsNone(manager.checker_task)
        self.assertTrue(any("simulated monitor crash" in event for event in manager.events))

    async def test_login_combines_session_check_failure_with_login_result(self):
        manager = self.make_task_manager()
        manager.api_handler.email = "user@example.com"
        manager.api_handler.password = "secret"
        manager.api_handler.is_session_expired = AsyncMock(side_effect=MarketplaceAPIError("network down"))
        manager.api_handler.login = AsyncMock(return_value=0)

        await manager.login()

        self.assertEqual(len(manager.events), 1)
        event_text = manager.events[0]
        self.assertIn("Session check failed: network down", event_text)
        self.assertIn("Login failed.", event_text)

    async def test_steam_mode_login_uses_browser_refresh_instead_of_credentials(self):
        manager = self.make_task_manager()
        manager.account_mode = STEAM_BROWSER_MODE
        manager.api_handler.account_mode = STEAM_BROWSER_MODE
        manager.api_handler.email = "user@example.com"
        manager.api_handler.password = "secret"
        manager.api_handler.is_session_expired = AsyncMock(return_value=-1)
        manager.api_handler.login = AsyncMock(return_value=1)
        manager.api_handler.validate_and_save_imported_session = AsyncMock(return_value=True)

        with patch(
            "bdo_marketplace_tools.services.task_manager.acquire_steam_market_cookies",
            new=AsyncMock(return_value=[{"name": "TradeAuth_Session", "value": "ok"}]),
        ) as browser_auth:
            await manager.login()

        browser_auth.assert_awaited_once()
        self.assertFalse(browser_auth.await_args.kwargs["auto_steam_login"])
        manager.api_handler.login.assert_not_called()
        manager.api_handler.validate_and_save_imported_session.assert_awaited_once()
        self.assertTrue(manager.api_handler.login_status)
        self.assertTrue(manager.saved_session_last_known_valid)
        self.assertTrue(manager.steam_auto_reauth_enabled)
        self.assertTrue(any("Steam Account session validated and saved" in event for event in manager.events))
        await manager.stop_login_status_checker()

    async def test_initial_steam_expired_session_prompts_without_enabling_auto_reauth(self):
        manager = self.make_task_manager()
        manager.account_mode = STEAM_BROWSER_MODE
        manager.api_handler.account_mode = STEAM_BROWSER_MODE
        manager.saved_session_last_known_valid = True
        manager.api_handler.session_has_cookies = True
        manager.api_handler.is_session_expired = AsyncMock(return_value=-1)

        with patch("bdo_marketplace_tools.services.task_manager.acquire_steam_market_cookies", new=AsyncMock()) as browser_auth:
            await manager.initial_login_check()

        browser_auth.assert_not_called()
        self.assertFalse(manager.api_handler.login_status)
        self.assertFalse(manager.steam_auto_reauth_enabled)
        self.assertFalse(manager.saved_session_last_known_valid)
        self.assertTrue(any("Refresh Session to open the login browser" in event for event in manager.events))

    async def test_initial_login_check_skips_api_without_last_known_valid_saved_session(self):
        manager = self.make_task_manager()
        manager.saved_session_last_known_valid = False
        manager.api_handler.session_has_cookies = True
        manager.api_handler.is_session_expired = AsyncMock(return_value=0)

        await manager.initial_login_check()

        manager.api_handler.is_session_expired.assert_not_called()
        self.assertFalse(manager.api_handler.login_status)
        self.assertTrue(any("No previously validated marketplace session" in event for event in manager.events))

    async def test_initial_login_check_clears_last_known_valid_when_cookies_are_missing(self):
        manager = self.make_task_manager()
        manager.saved_session_last_known_valid = True
        manager.api_handler.session_has_cookies = False
        manager.api_handler.is_session_expired = AsyncMock(return_value=0)

        await manager.initial_login_check()

        manager.api_handler.is_session_expired.assert_not_called()
        self.assertFalse(manager.saved_session_last_known_valid)
        self.assertFalse(manager.api_handler.login_status)
        self.assertTrue(any("No saved marketplace session cookies found" in event for event in manager.events))

    async def test_initial_valid_steam_session_enables_auto_reauth_for_current_run(self):
        manager = self.make_task_manager()
        manager.account_mode = STEAM_BROWSER_MODE
        manager.api_handler.account_mode = STEAM_BROWSER_MODE
        manager.saved_session_last_known_valid = True
        manager.api_handler.session_has_cookies = True
        manager.api_handler.is_session_expired = AsyncMock(return_value=0)

        await manager.initial_login_check()

        self.assertTrue(manager.api_handler.login_status)
        self.assertTrue(manager.saved_session_last_known_valid)
        self.assertTrue(manager.steam_auto_reauth_enabled)
        self.assertTrue(any("Saved marketplace session is valid" in event for event in manager.events))
        await manager.stop_login_status_checker()

    async def test_first_time_steam_refresh_prepares_profile_before_market_cookie_import(self):
        manager = self.make_task_manager()
        manager.account_mode = STEAM_BROWSER_MODE
        manager.api_handler.account_mode = STEAM_BROWSER_MODE
        manager.steam_browser_profile_prepared = False
        manager.api_handler.validate_and_save_imported_session = AsyncMock(return_value=True)

        with patch("bdo_marketplace_tools.services.task_manager.prepare_steam_browser_profile", new=AsyncMock()) as profile_setup, patch(
            "bdo_marketplace_tools.services.task_manager.save_steam_browser_profile_prepared",
            return_value=True,
        ) as save_prepared, patch(
            "bdo_marketplace_tools.services.task_manager.acquire_steam_market_cookies",
            new=AsyncMock(return_value=[{"name": "TradeAuth_Session", "value": "ok"}]),
        ) as browser_auth:
            refreshed = await manager.refresh_browser_session()

        self.assertTrue(refreshed)
        profile_setup.assert_awaited_once()
        save_prepared.assert_called_once_with(True)
        browser_auth.assert_awaited_once()
        self.assertFalse(browser_auth.await_args.kwargs["auto_steam_login"])
        manager.api_handler.validate_and_save_imported_session.assert_awaited_once()
        self.assertTrue(manager.steam_browser_profile_prepared)
        self.assertTrue(manager.saved_session_last_known_valid)
        self.assertTrue(manager.steam_auto_reauth_enabled)
        self.assertTrue(any("Initial Steam browser setup is required" in event for event in manager.events))
        self.assertTrue(any("Initial Steam browser setup saved" in event for event in manager.events))
        await manager.stop_login_status_checker()

    async def test_failed_steam_refresh_clears_last_known_valid_session_flag(self):
        manager = self.make_task_manager()
        manager.account_mode = STEAM_BROWSER_MODE
        manager.api_handler.account_mode = STEAM_BROWSER_MODE
        manager.saved_session_last_known_valid = True

        with patch(
            "bdo_marketplace_tools.services.task_manager.acquire_steam_market_cookies",
            new=AsyncMock(side_effect=BrowserAuthError("browser closed")),
        ):
            refreshed = await manager.refresh_browser_session()

        self.assertFalse(refreshed)
        self.assertFalse(manager.saved_session_last_known_valid)
        self.assertFalse(manager.api_handler.login_status)

    async def test_account_mode_change_stops_monitor_and_clears_session(self):
        manager = self.make_task_manager()
        manager.api_handler.login_status = True
        manager.purchase_submission_enabled = True
        manager.steam_auto_reauth_enabled = True
        manager.saved_session_last_known_valid = True

        async def idle_checker():
            await asyncio.sleep(60)

        manager.checker = idle_checker
        await manager.start_checker()
        self.assertTrue(manager.checker_enabled)

        changed = await manager.change_account_mode(STEAM_BROWSER_MODE)

        self.assertTrue(changed)
        self.assertFalse(manager.checker_enabled)
        self.assertFalse(manager.purchase_submission_enabled)
        self.assertFalse(manager.api_handler.login_status)
        self.assertTrue(manager.api_handler.session_cleared)
        self.assertFalse(manager.steam_auto_reauth_enabled)
        self.assertFalse(manager.saved_session_last_known_valid)
        self.assertTrue(any("Marketplace session cleared" in event for event in manager.events))

    async def test_account_mode_change_during_purchase_defers_session_clear_until_chain_finishes(self):
        manager = self.make_task_manager()
        manager.api_handler.login_status = True
        manager.purchase_submission_enabled = True
        manager.steam_auto_reauth_enabled = True
        manager.saved_session_last_known_valid = True
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_buy(*args, **kwargs):
            started.set()
            await release.wait()
            return {"purchase_records": [], "events": [{"level": "success", "message": "buy chain done"}]}

        manager.api_handler.buy_item = slow_buy
        buy_task = asyncio.create_task(manager.buy_item([["10007", "1", "82500"]], adjust_pricing=False))
        await started.wait()

        changed = await manager.change_account_mode(STEAM_BROWSER_MODE)

        self.assertTrue(changed)
        self.assertTrue(manager.purchase_in_progress)
        self.assertFalse(manager.api_handler.session_cleared)
        self.assertIsNotNone(manager.pending_auth_reset_reason)

        release.set()
        await buy_task

        self.assertFalse(manager.purchase_in_progress)
        self.assertIsNone(manager.pending_auth_reset_reason)
        self.assertFalse(manager.api_handler.login_status)
        self.assertTrue(manager.api_handler.session_cleared)
        self.assertFalse(manager.steam_auto_reauth_enabled)
        self.assertFalse(manager.saved_session_last_known_valid)
        self.assertTrue(any("buy chain done" in event for event in manager.events))
        self.assertTrue(any("Marketplace session cleared" in event for event in manager.events))

    async def test_debug_session_invalidation_keeps_running_monitor_and_buy_mode(self):
        manager = self.make_task_manager(test_mode_enabled=True)
        manager.api_handler.login_status = True
        manager.purchase_submission_enabled = True
        manager.saved_session_last_known_valid = True

        async def idle_checker():
            await asyncio.sleep(60)

        manager.checker = idle_checker
        await manager.start_checker()
        self.assertTrue(manager.checker_enabled)

        invalidated = manager.debug_invalidate_marketplace_session()

        self.assertTrue(invalidated)
        self.assertTrue(manager.checker_enabled)
        self.assertTrue(manager.purchase_submission_enabled)
        self.assertTrue(manager.api_handler.login_status)
        self.assertFalse(manager.api_handler.session_cleared)
        self.assertTrue(manager.debug_force_purchase_session_expired)
        self.assertFalse(manager.saved_session_last_known_valid)
        self.assertEqual(len(manager.events), 0)

        await manager.stop_checker()

    async def test_debug_session_invalidation_enables_auto_reauth_for_online_steam_session(self):
        manager = self.make_task_manager(test_mode_enabled=True)
        manager.account_mode = STEAM_BROWSER_MODE
        manager.api_handler.account_mode = STEAM_BROWSER_MODE
        manager.api_handler.login_status = True
        manager.saved_session_last_known_valid = True

        invalidated = manager.debug_invalidate_marketplace_session()

        self.assertTrue(invalidated)
        self.assertTrue(manager.debug_force_purchase_session_expired)
        self.assertTrue(manager.steam_auto_reauth_enabled)
        self.assertTrue(manager.api_handler.login_status)
        self.assertFalse(manager.saved_session_last_known_valid)

    async def test_debug_toggle_steam_auto_reauth_requires_test_mode_and_steam_mode(self):
        manager = self.make_task_manager(test_mode_enabled=False)
        manager.account_mode = STEAM_BROWSER_MODE
        manager.api_handler.account_mode = STEAM_BROWSER_MODE

        self.assertIsNone(manager.debug_toggle_steam_auto_reauth())
        self.assertFalse(manager.steam_auto_reauth_enabled)

        manager = self.make_task_manager(test_mode_enabled=True)
        self.assertIsNone(manager.debug_toggle_steam_auto_reauth())
        self.assertFalse(manager.steam_auto_reauth_enabled)

        manager.account_mode = STEAM_BROWSER_MODE
        manager.api_handler.account_mode = STEAM_BROWSER_MODE
        self.assertTrue(manager.debug_toggle_steam_auto_reauth())
        self.assertTrue(manager.steam_auto_reauth_enabled)
        self.assertFalse(manager.debug_toggle_steam_auto_reauth())
        self.assertFalse(manager.steam_auto_reauth_enabled)

    async def test_debug_reauthentication_check_simulates_purchase_expiry_and_pa_relogin(self):
        manager = self.make_task_manager(test_mode_enabled=True)
        manager.api_handler.login_status = True
        manager.purchase_submission_enabled = True
        manager.debug_invalidate_marketplace_session()
        manager.api_handler.login = AsyncMock(return_value=1)
        manager.api_handler.save_session = Mock()

        recovered = await manager.debug_run_reauthentication_check()

        self.assertTrue(recovered)
        manager.api_handler.login.assert_awaited_once()
        manager.api_handler.save_session.assert_called_once()
        self.assertTrue(manager.api_handler.login_status)
        self.assertTrue(manager.purchase_submission_enabled)
        self.assertFalse(manager.debug_force_purchase_session_expired)
        self.assertTrue(any("Simulated purchase response: login session expired" in event for event in manager.events))
        self.assertTrue(any("Re-authentication succeeded. Retrying purchase request" in event for event in manager.events))

    async def test_debug_reauthentication_check_uses_browser_refresh_in_steam_mode(self):
        manager = self.make_task_manager(test_mode_enabled=True)
        manager.account_mode = STEAM_BROWSER_MODE
        manager.api_handler.account_mode = STEAM_BROWSER_MODE
        manager.purchase_submission_enabled = True
        manager.api_handler.login = AsyncMock(return_value=1)
        manager.refresh_browser_session = AsyncMock(return_value=True)

        recovered = await manager.debug_run_reauthentication_check()

        self.assertTrue(recovered)
        manager.api_handler.login.assert_not_called()
        manager.refresh_browser_session.assert_awaited_once()
        self.assertTrue(manager.purchase_submission_enabled)
        self.assertTrue(any("Re-authentication succeeded. Retrying purchase request" in event for event in manager.events))

    async def test_debug_blank_browser_diagnostic_opens_without_session_import(self):
        manager = self.make_task_manager(test_mode_enabled=True)

        with patch("bdo_marketplace_tools.services.task_manager.open_blank_steam_browser_diagnostic", new=AsyncMock()) as browser_diag:
            opened = await manager.debug_open_blank_browser_diagnostic()

        self.assertTrue(opened)
        browser_diag.assert_awaited_once()
        self.assertFalse(manager.api_handler.session_cleared)
        self.assertFalse(manager.api_handler.login_status)
        self.assertTrue(any("Blank browser diagnostic closed" in event for event in manager.events))

    async def test_steam_buy_expired_response_refreshes_browser_and_retries_once(self):
        manager = self.make_task_manager()
        manager.account_mode = STEAM_BROWSER_MODE
        manager.api_handler.account_mode = STEAM_BROWSER_MODE
        manager.purchase_submission_enabled = True
        expired_summary = {
            "purchase_records": [],
            "results": [{"item_id": "10007", "result_code": 2000}],
            "events": [{"level": "error", "message": "Login session expired."}],
        }
        success_summary = {
            "purchase_records": [{"item_id": "10007", "price": 82500, "count": 1, "result_code": 0}],
            "results": [{"item_id": "10007", "result_code": 0}],
            "events": [{"level": "success", "message": "Purchase succeeded after retry."}],
        }
        manager.api_handler.buy_item = AsyncMock(side_effect=[expired_summary, success_summary])
        manager.refresh_browser_session = AsyncMock(return_value=True)

        with patch.object(manager, "save_local_data") as save_mock:
            await manager.buy_item([["10007", "1", "82500"]], adjust_pricing=False)

        self.assertEqual(manager.api_handler.buy_item.await_count, 2)
        manager.refresh_browser_session.assert_awaited_once()
        self.assertTrue(manager.purchase_submission_enabled)
        self.assertEqual(manager.session_successful_purchases, 1)
        self.assertTrue(any("Purchase succeeded after retry" in event for event in manager.events))
        save_mock.assert_called_once()

    async def test_steam_buy_expired_response_uses_enabled_auto_reauth_flow(self):
        manager = self.make_task_manager()
        manager.account_mode = STEAM_BROWSER_MODE
        manager.api_handler.account_mode = STEAM_BROWSER_MODE
        manager.steam_auto_reauth_enabled = True
        manager.purchase_submission_enabled = True
        manager.api_handler.validate_and_save_imported_session = AsyncMock(return_value=True)
        expired_summary = {
            "purchase_records": [],
            "results": [{"item_id": "10007", "result_code": 2000}],
            "events": [{"level": "error", "message": "Login session expired."}],
        }
        success_summary = {
            "purchase_records": [{"item_id": "10007", "price": 82500, "count": 1, "result_code": 0}],
            "results": [{"item_id": "10007", "result_code": 0}],
            "events": [{"level": "success", "message": "Purchase succeeded after auto re-auth."}],
        }
        manager.api_handler.buy_item = AsyncMock(side_effect=[expired_summary, success_summary])

        with patch(
            "bdo_marketplace_tools.services.task_manager.acquire_steam_market_cookies",
            new=AsyncMock(return_value=[{"name": "TradeAuth_Session", "value": "ok"}]),
        ) as browser_auth:
            with patch.object(manager, "save_local_data"):
                await manager.buy_item([["10007", "1", "82500"]], adjust_pricing=False)

        self.assertEqual(manager.api_handler.buy_item.await_count, 2)
        browser_auth.assert_awaited_once()
        self.assertTrue(browser_auth.await_args.kwargs["auto_steam_login"])
        self.assertTrue(manager.purchase_submission_enabled)
        self.assertTrue(any("Purchase succeeded after auto re-auth" in event for event in manager.events))
        await manager.stop_login_status_checker()

    async def test_login_status_checker_combines_expired_session_with_reauth_result(self):
        manager = self.make_task_manager()
        manager.api_handler.is_session_expired = AsyncMock(return_value=-1)
        manager.api_handler.login = AsyncMock(return_value=0)

        with patch("bdo_marketplace_tools.services.task_manager.asyncio.sleep", new=AsyncMock(return_value=None)):
            await manager.login_status_checker()

        self.assertEqual(len(manager.events), 1)
        self.assertIn("Session expired. Re-authentication failed.", manager.events[0])

    async def test_login_status_checker_prompts_browser_refresh_in_steam_mode(self):
        manager = self.make_task_manager()
        manager.account_mode = STEAM_BROWSER_MODE
        manager.api_handler.account_mode = STEAM_BROWSER_MODE
        manager.api_handler.is_session_expired = AsyncMock(return_value=-1)
        manager.api_handler.login = AsyncMock(return_value=1)
        manager.purchase_submission_enabled = True
        manager.refresh_browser_session = AsyncMock(return_value=True)

        with patch("bdo_marketplace_tools.services.task_manager.asyncio.sleep", new=AsyncMock(return_value=None)):
            await manager.login_status_checker()

        manager.api_handler.login.assert_not_called()
        manager.refresh_browser_session.assert_not_called()
        self.assertFalse(manager.purchase_submission_enabled)
        self.assertTrue(any("Steam Account refresh required" in event for event in manager.events))

    async def test_expired_steam_session_auto_reauths_when_current_run_gate_is_enabled(self):
        manager = self.make_task_manager()
        manager.account_mode = STEAM_BROWSER_MODE
        manager.api_handler.account_mode = STEAM_BROWSER_MODE
        manager.steam_auto_reauth_enabled = True
        manager.purchase_submission_enabled = True

        async def refresh_side_effect(*args, **kwargs):
            manager.api_handler.login_status = True
            return True

        manager.refresh_browser_session = AsyncMock(side_effect=refresh_side_effect)

        recovered = await manager.handle_expired_session()

        self.assertTrue(recovered)
        manager.refresh_browser_session.assert_awaited_once_with(auto_steam_login=True)
        self.assertTrue(manager.purchase_submission_enabled)
        self.assertTrue(manager.api_handler.login_status)
        self.assertTrue(any("automatic Steam Account re-authentication" in event for event in manager.events))


class TextualAppTests(unittest.IsolatedAsyncioTestCase):
    def make_app(self, launch_mode="live"):
        with patch("bdo_marketplace_tools.services.task_manager._load_local_data", return_value=LOCAL_DATA.copy()), patch(
            "bdo_marketplace_tools.services.task_manager.load_account_mode",
            return_value=PA_CREDENTIALS_MODE,
        ), patch("bdo_marketplace_tools.services.task_manager.load_steam_browser_profile_prepared", return_value=True):
            manager = BackgroundTasks(FakeAPI(), persist_ui_settings=False)
        return MarketplaceToolsApp(manager, manager.api_handler, launch_mode=launch_mode)

    async def test_app_launches_and_navigates_sidebar(self):
        app = self.make_app()
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(100, 36)) as pilot:
                self.assertEqual(app.current_view, "dashboard")
                self.assertEqual(app.theme, DEFAULT_THEME)
                self.assertEqual(len(list(app.query("AppHeader"))), 1)
                self.assertEqual(len(list(app.query("HeaderIcon"))), 0)
                self.assertEqual(len(list(app.query("HeaderClock"))), 1)
                await pilot.click("#app-header")
                self.assertFalse(app.query_one("#app-header").has_class("-tall"))
                self.assertEqual(app.query_one("#banner").render(), BANNER_ART)
                self.assertTrue(app.query_one("#banner").display)
                self.assertFalse(app.query_one("#screen-title").display)
                await pilot.press("1")
                self.assertEqual(app.current_view, "settings")
                self.assertFalse(app.query_one("#banner").display)
                self.assertTrue(app.query_one("#screen-title").display)
                await pilot.press("2")
                self.assertEqual(app.current_view, "wallet")
                self.assertIn(("wallet", "Inventory"), app.NAV_ITEMS)
                self.assertEqual(app.query_one("#screen-title", Static).content, "Marketplace Inventory")
                await pilot.press("3")
                self.assertEqual(app.current_view, "stats")
                self.assertEqual(len(list(app.query("#stats-output"))), 0)
                self.assertEqual(len(list(app.query(".stats-tile"))), 6)
                await pilot.press("escape")
                self.assertEqual(app.current_view, "dashboard")
                self.assertTrue(app.query_one("#banner").display)

    async def test_dashboard_banner_shows_when_terminal_is_large_enough(self):
        app = self.make_app()
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(150, 45)):
                self.assertEqual(app.current_view, "dashboard")
                self.assertTrue(app.query_one("#banner").display)

    async def test_dashboard_content_remains_scrollable(self):
        app = self.make_app()
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(100, 36)):
                self.assertEqual(app.current_view, "dashboard")
                self.assertEqual(app.query_one("#content").styles.overflow_y, "auto")
                self.assertGreaterEqual(app.query_one("#event-log").size.height, 6)
                self.assertLessEqual(app.query_one("#sidebar").region.width, 23)
                self.assertEqual(app.query_one("#event-log").styles.border_title_color, Color(255, 145, 60))

    async def test_credentials_validation_and_password_masking(self):
        app = self.make_app()
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)), patch(
            "bdo_marketplace_tools.ui.app.save_credentials"
        ) as save_mock:
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.click("#tile-credentials")
                await pilot.pause()
                self.assertEqual(len(list(app.screen_stack[-1].query("#email-input"))), 0)
                self.assertEqual(len(list(app.screen_stack[-1].query("#password-input"))), 0)

                await pilot.click("#credential-action-tile")
                await pilot.pause()
                password_input = app.query_visible_one("#password-input")
                self.assertTrue(password_input.password)
                self.assertTrue(app.query_visible_one("#save-pa-credentials", Button).disabled)

                app.query_visible_one("#email-input").value = "user@example.com"
                await pilot.pause()
                self.assertTrue(app.query_visible_one("#save-pa-credentials", Button).disabled)

                app.query_visible_one("#password-input").value = "secret"
                await pilot.pause()
                self.assertFalse(app.query_visible_one("#save-pa-credentials", Button).disabled)
                await pilot.click("#save-pa-credentials")
                save_mock.assert_called_once_with("user@example.com", "secret")
                self.assertIn("Credentials saved", app.status_message)
                self.assertEqual(type(app.screen_stack[-1]).__name__, "CredentialsModal")

    async def test_pa_credentials_modal_shows_invalid_email_warning_inline(self):
        app = self.make_app()
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)), patch(
            "bdo_marketplace_tools.ui.app.save_credentials"
        ) as save_mock:
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.click("#tile-credentials")
                await pilot.pause()
                await pilot.click("#credential-action-tile")
                await pilot.pause()
                app.query_visible_one("#email-input").value = "not-an-email"
                app.query_visible_one("#password-input").value = "secret"
                await pilot.pause()
                self.assertFalse(app.query_visible_one("#save-pa-credentials", Button).disabled)

                await pilot.click("#save-pa-credentials")
                await pilot.pause()

                self.assertIn(
                    "Enter a valid email address",
                    str(app.query_visible_one("#pa-credentials-warning", Static).render()),
                )
                self.assertEqual(app.status_message, "")
                save_mock.assert_not_called()

    async def test_saved_credentials_are_labeled_set_not_authenticated_ready(self):
        app = self.make_app()
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=("user@example.com", "secret")):
            async with app.run_test(size=(100, 36)):
                credential_status, credential_detail, credential_level, _, _ = app.credential_state()

        self.assertEqual(credential_status, "Set")
        self.assertEqual(credential_detail, "us**@example.com")
        self.assertEqual(credential_level, "success")

    async def test_app_settings_clear_saved_session_button_resets_marketplace_session(self):
        app = self.make_app()
        app.api_handler.login_status = True
        app.task_manager.purchase_submission_enabled = True

        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.press("1")
                self.assertEqual(app.current_view, "settings")
                self.assertEqual(len(list(app.query("#clear-saved-session"))), 1)

                await pilot.click("#clear-saved-session")
                await pilot.pause(0.1)

        self.assertTrue(app.api_handler.session_cleared)
        self.assertFalse(app.api_handler.login_status)
        self.assertFalse(app.task_manager.purchase_submission_enabled)
        self.assertIn("Saved marketplace session cleared", app.status_message)
        self.assertTrue(any("Manual session reset. Marketplace session cleared" in event for event in app.task_manager.events))

    async def test_dashboard_live_metrics_refresh(self):
        app = self.make_app()
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(100, 36)) as pilot:
                app.task_manager.session_detected_outfits = 4
                app.task_manager.session_successful_purchases = 2
                app.task_manager.session_silver_spent = 1_500_000_000
                app.refresh_live_widgets()

                rendered_tiles = []
                for tile_id in ("monitor", "spent", "credentials", "session", "polling", "buy-delay", "success", "runtime"):
                    tile = app.query_one(f"#tile-{tile_id}", DashboardTile)
                    rendered_tiles.append(str(tile.border_title))
                rendered_tiles.extend(
                    f"{tile_id} {value} {detail}"
                    for tile_id, value, detail, _level, _show_dot in app.dashboard_tile_data(app.dashboard_snapshot())
                )
                rendered_tiles = "\n".join(rendered_tiles)
                self.assertIn("Monitor", rendered_tiles)
                self.assertIn("Success Rate", rendered_tiles)
                self.assertIn("Spent", rendered_tiles)
                self.assertIn("Credentials", rendered_tiles)
                self.assertIn("Session", rendered_tiles)
                self.assertIn("Polling", rendered_tiles)
                self.assertIn("Buy Delay", rendered_tiles)
                self.assertIn("Runtime", rendered_tiles)
                self.assertIn("No account", rendered_tiles)
                self.assertIn("Marketplace auth", rendered_tiles)
                self.assertIn("15-30s", rendered_tiles)
                self.assertIn("Slow", rendered_tiles)
                self.assertIn("1-2.5s", rendered_tiles)
                self.assertIn("Between buys", rendered_tiles)
                self.assertIn("2/4 bought", rendered_tiles)
                self.assertIn("50%", rendered_tiles)
                self.assertIn("1.5B silver", rendered_tiles)
                self.assertIs(app.query_one("#tile-session").parent, app.query_one("#dashboard-monitor-column"))
                self.assertIs(app.query_one("#tile-buy-delay").parent, app.query_one("#dashboard-delay-column"))

                await pilot.click("#tile-monitor")
                await pilot.pause()
                monitor_note = str(app.query_visible_one(".modal-note", Static).render())
                self.assertIn("online marketplace session", monitor_note)
                self.assertIn("refresh Session from the dashboard", monitor_note)
                await pilot.press("escape")
                await pilot.click("#tile-spent")
                await pilot.pause()
                self.assertEqual(app.current_view, "dashboard")
                self.assertEqual(app.query_visible_one("#spend-cap-input", Input).value, "0")
                self.assertEqual(len(list(app.screen_stack[-1].query("#spend-summary"))), 1)
                self.assertEqual(len(list(app.screen_stack[-1].query("#settings-summary"))), 0)
                await pilot.click("#save-spend-cap")
                await pilot.pause()
                self.assertEqual([type(screen).__name__ for screen in app.screen_stack], ["Screen"])
                await pilot.click("#tile-spent")
                await pilot.pause()
                await pilot.press("escape")
                await pilot.click("#tile-credentials")
                await pilot.pause()
                self.assertEqual(app.current_view, "dashboard")
                self.assertEqual(len(list(app.screen_stack[-1].query("#password-input"))), 0)
                await pilot.click("#credential-action-tile")
                await pilot.pause()
                self.assertTrue(app.query_visible_one("#password-input", Input).password)
                await pilot.press("escape")
                await pilot.press("escape")
                await pilot.click("#tile-polling")
                await pilot.pause()
                self.assertEqual(app.current_view, "dashboard")
                self.assertEqual(len(list(app.screen_stack[-1].query("#delay-select"))), 0)
                self.assertEqual(len(list(app.screen_stack[-1].query("#polling-summary"))), 0)
                polling_note = str(app.query_visible_one(".modal-note", Static).render())
                self.assertIn("how often the app checks the marketplace", polling_note)
                self.assertEqual(len(list(app.screen_stack[-1].query("#polling-recommendations"))), 1)
                self.assertEqual(len(list(app.screen_stack[-1].query("#polling-preset-1"))), 1)
                self.assertEqual(len(list(app.screen_stack[-1].query("#polling-preset-2"))), 1)
                self.assertEqual(len(list(app.screen_stack[-1].query("#polling-preset-3"))), 1)
                self.assertIn("modal-info-clickable", app.query_visible_one("#polling-preset-2").classes)
                self.assertIn("preset-selected", app.query_visible_one("#polling-preset-3").classes)
                self.assertEqual(len(list(app.screen_stack[-1].query("#settings-summary"))), 0)
                await pilot.click("#polling-preset-2")
                await pilot.pause()
                self.assertEqual(app.query_visible_one("#custom-delay-min-input", Input).value, "5")
                self.assertEqual(app.query_visible_one("#custom-delay-max-input", Input).value, "10")
                self.assertIn("preset-selected", app.query_visible_one("#polling-preset-2").classes)
                app.query_visible_one("#custom-delay-min-input", Input).value = "8"
                app.query_visible_one("#custom-delay-max-input", Input).value = "13"
                await pilot.pause()
                self.assertNotIn("preset-selected", app.query_visible_one("#polling-preset-2").classes)
                app.query_visible_one("#custom-delay-min-input", Input).value = "5"
                app.query_visible_one("#custom-delay-max-input", Input).value = "10"
                await pilot.pause()
                self.assertIn("preset-selected", app.query_visible_one("#polling-preset-2").classes)
                app.query_visible_one("#custom-delay-min-input", Input).value = "8"
                app.query_visible_one("#custom-delay-max-input", Input).value = "13"
                await pilot.click("#save-polling")
                await pilot.pause()
                self.assertEqual(app.task_manager.delay, "custom")
                self.assertEqual(app.task_manager.current_delay_bounds(), (8, 13))
                self.assertEqual([type(screen).__name__ for screen in app.screen_stack], ["Screen"])
                await pilot.click("#tile-polling")
                await pilot.pause()
                await pilot.press("escape")
                await pilot.click("#tile-buy-delay")
                await pilot.pause()
                self.assertEqual(app.query_visible_one("#purchase-delay-min-input", Input).value, "1")
                self.assertEqual(app.query_visible_one("#purchase-delay-max-input", Input).value, "2.5")
                buy_delay_note = str(app.query_visible_one(".modal-note", Static).render())
                self.assertIn("between each purchase attempt", buy_delay_note)
                self.assertIn("does not change how often the app scans", buy_delay_note)
                await pilot.press("escape")
                await pilot.click("#tile-session")
                await pilot.pause()
                self.assertEqual(app.current_view, "dashboard")
                self.assertEqual(type(app.screen_stack[-1]).__name__, "SessionRefreshConfirmScreen")
                await pilot.press("escape")
                await pilot.click("#tile-success")
                self.assertEqual(app.current_view, "dashboard")
                await pilot.click("#tile-runtime")
                self.assertEqual(app.current_view, "dashboard")

    async def test_credentials_modal_can_select_steam_browser_session_mode(self):
        app = self.make_app()
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)), patch(
            "bdo_marketplace_tools.services.task_manager.save_account_mode",
            return_value=STEAM_BROWSER_MODE,
        ):
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.press("1")
                self.assertEqual(len(list(app.query("#account-mode-select"))), 0)
                self.assertEqual(len(list(app.query("#save-settings"))), 0)

                await pilot.press("escape")
                await pilot.click("#tile-credentials")
                await pilot.pause()
                mode_select = app.query_visible_one("#account-mode-select", Select)
                self.assertIn("OS keyring password", str(app.query_visible_one("#credentials-mode-note", Static).render()))
                self.assertEqual(len(list(app.query("#credentials-email-tile"))), 0)
                self.assertEqual(len(list(app.query("#credentials-password-tile"))), 0)
                self.assertEqual(len(list(app.query("#credentials-status-tile"))), 0)
                self.assertEqual(len(list(app.screen_stack[-1].query("#email-input"))), 0)
                self.assertEqual(len(list(app.screen_stack[-1].query("#password-input"))), 0)
                setup_tile_widget = app.query_visible_one("#credential-action-tile", Static)
                self.assertEqual(setup_tile_widget.border_title, "Pearl Abyss Account")
                self.assertTrue(setup_tile_widget.display)
                self.assertIn("modal-info-clickable", setup_tile_widget.classes)
                console = Console(width=100, color_system=None)
                with console.capture() as capture:
                    console.print(setup_tile_widget.content)
                setup_tile = capture.get()
                self.assertIn("No account configured", setup_tile)
                self.assertIn("Click to enter credentials", setup_tile)
                mode_select.value = STEAM_BROWSER_MODE
                await pilot.pause()
                self.assertTrue(app.task_manager.uses_steam_browser_session())
                self.assertEqual(app.api_handler.account_mode, STEAM_BROWSER_MODE)
                self.assertEqual(setup_tile_widget.border_title, "Steam Initial Setup")
                self.assertTrue(setup_tile_widget.display)
                self.assertNotIn("modal-info-clickable", setup_tile_widget.classes)
                self.assertIn("modal-info-muted", setup_tile_widget.classes)
                self.assertEqual(len(list(app.screen_stack[-1].query("#email-input"))), 0)
                self.assertEqual(len(list(app.screen_stack[-1].query("#password-input"))), 0)
                self.assertEqual(len(list(app.screen_stack[-1].query("#save-credential-mode"))), 0)
                steam_note = str(app.query_visible_one("#credentials-mode-note", Static).render())
                self.assertIn("visible browser", steam_note)
                self.assertIn("does not use saved email or password", steam_note)

                self.assertTrue(app.task_manager.uses_steam_browser_session())
                self.assertEqual(app.api_handler.account_mode, STEAM_BROWSER_MODE)
                self.assertIn("Login method set to Steam Account", app.status_message)
                self.assertEqual(app.credential_state()[0], "Steam Account")
                self.assertEqual(app.session_status_state(), ("OFFLINE", "Refresh required", "warning"))
                self.assertEqual(type(app.screen_stack[-1]).__name__, "CredentialsModal")

    async def test_credentials_modal_shows_initial_steam_setup_only_until_profile_prepared(self):
        app = self.make_app()
        app.task_manager.steam_browser_profile_prepared = False

        async def mark_prepared(*_args, **_kwargs):
            app.task_manager.steam_browser_profile_prepared = True
            return True

        app.task_manager.prepare_steam_browser_profile = AsyncMock(side_effect=mark_prepared)
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)), patch(
            "bdo_marketplace_tools.services.task_manager.save_account_mode",
            return_value=STEAM_BROWSER_MODE,
        ) as save_mode:
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.press("escape")
                await pilot.click("#tile-credentials")
                await pilot.pause()

                self.assertEqual(len(list(app.query("#prepare-steam-profile"))), 0)
                setup_tile_widget = app.query_visible_one("#credential-action-tile", Static)
                self.assertEqual(setup_tile_widget.border_title, "Pearl Abyss Account")
                self.assertTrue(setup_tile_widget.display)
                console = Console(width=100, color_system=None)
                with console.capture() as capture:
                    console.print(setup_tile_widget.content)
                setup_tile = capture.get()
                self.assertIn("No account configured", setup_tile)
                self.assertIn("Click to enter credentials", setup_tile)

                mode_select = app.query_visible_one("#account-mode-select", Select)
                mode_select.value = STEAM_BROWSER_MODE
                await pilot.pause()

                self.assertEqual(app.task_manager.account_mode, STEAM_BROWSER_MODE)
                self.assertEqual(setup_tile_widget.border_title, "Steam Initial Setup")
                self.assertTrue(setup_tile_widget.display)
                self.assertIn("modal-info-clickable", setup_tile_widget.classes)
                self.assertNotIn("modal-info-muted", setup_tile_widget.classes)
                self.assertEqual(len(list(app.screen_stack[-1].query("#save-credential-mode"))), 0)
                self.assertIn("Run Steam Setup once", str(app.query_visible_one("#credentials-mode-note", Static).render()))

                await pilot.click("#credential-action-tile")
                await pilot.pause(0.2)

                app.task_manager.prepare_steam_browser_profile.assert_awaited_once_with(allow_inactive_mode=True)
                save_mode.assert_called_once_with(STEAM_BROWSER_MODE)
                self.assertEqual(app.task_manager.account_mode, STEAM_BROWSER_MODE)
                self.assertTrue(app.task_manager.steam_browser_profile_prepared)
                self.assertTrue(setup_tile_widget.display)
                self.assertNotIn("modal-info-clickable", setup_tile_widget.classes)
                self.assertIn("modal-info-muted", setup_tile_widget.classes)
                with console.capture() as capture:
                    console.print(app.query_visible_one("#credential-action-tile", Static).content)
                setup_tile = capture.get()
                self.assertIn("Complete", setup_tile)
                self.assertIn("Ready for market login", setup_tile)
                self.assertIn("Initial Steam setup saved", app.status_message)

    async def test_switching_back_to_pa_mode_reuses_saved_credentials(self):
        app = self.make_app()
        app.task_manager.account_mode = STEAM_BROWSER_MODE
        app.api_handler.account_mode = STEAM_BROWSER_MODE
        app.task_manager.steam_browser_profile_prepared = True

        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=("user@example.com", "secret")), patch(
            "bdo_marketplace_tools.ui.app.save_credentials"
        ) as save_mock, patch("bdo_marketplace_tools.services.task_manager.save_account_mode", return_value=PA_CREDENTIALS_MODE):
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.click("#tile-credentials")
                await pilot.pause()
                self.assertEqual(len(list(app.screen_stack[-1].query("#email-input"))), 0)
                self.assertEqual(len(list(app.screen_stack[-1].query("#password-input"))), 0)

                mode_select = app.query_visible_one("#account-mode-select", Select)
                mode_select.value = PA_CREDENTIALS_MODE
                await pilot.pause()
                setup_tile_widget = app.query_visible_one("#credential-action-tile", Static)
                self.assertEqual(setup_tile_widget.border_title, "Pearl Abyss Account")
                self.assertIn("modal-info-clickable", setup_tile_widget.classes)
                self.assertEqual(len(list(app.screen_stack[-1].query("#save-credential-mode"))), 0)

        save_mock.assert_not_called()
        self.assertEqual(app.task_manager.account_mode, PA_CREDENTIALS_MODE)
        self.assertEqual(app.api_handler.email, "user@example.com")
        self.assertEqual(app.api_handler.password, "secret")
        self.assertIn("Login method set to Pearl Abyss Account", app.status_message)

    async def test_buy_delay_modal_saves_valid_decimals_and_keeps_invalid_open(self):
        app = self.make_app()
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.click("#tile-buy-delay")
                await pilot.pause()
                self.assertEqual(app.task_manager.purchase_delay_range(), "1-2.5s")
                self.assertEqual(app.query_visible_one("#purchase-delay-min-input", Input).value, "1")
                self.assertEqual(app.query_visible_one("#purchase-delay-max-input", Input).value, "2.5")

                app.query_visible_one("#purchase-delay-min-input", Input).value = "4.5"
                app.query_visible_one("#purchase-delay-max-input", Input).value = "8"
                await pilot.click("#save-buy-delay")
                await pilot.pause()
                self.assertEqual(app.task_manager.purchase_delay_bounds, (4.5, 8.0))
                self.assertIn("Buy delay saved: 4.5-8s", app.status_message)
                self.assertEqual([type(screen).__name__ for screen in app.screen_stack], ["Screen"])

                await pilot.click("#tile-buy-delay")
                await pilot.pause()
                app.query_visible_one("#purchase-delay-min-input", Input).value = "10"
                app.query_visible_one("#purchase-delay-max-input", Input).value = "2"
                await pilot.click("#save-buy-delay")
                await pilot.pause()
                self.assertEqual(app.task_manager.purchase_delay_bounds, (4.5, 8.0))
                self.assertIn("Buy delay must use non-negative seconds", app.status_message)
                self.assertEqual(type(app.screen_stack[-1]).__name__, "BuyDelayModal")

    async def test_modal_input_edits_do_not_apply_until_save(self):
        app = self.make_app()
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.click("#tile-polling")
                await pilot.pause()
                await pilot.click("#polling-preset-2")
                await pilot.pause()
                self.assertEqual(app.query_visible_one("#custom-delay-min-input", Input).value, "5")
                self.assertEqual(app.query_visible_one("#custom-delay-max-input", Input).value, "10")
                self.assertIn("preset-selected", app.query_visible_one("#polling-preset-2").classes)
                self.assertEqual(app.task_manager.delay, "3")
                self.assertEqual(app.task_manager.current_delay_bounds(), (15, 30))
                app.query_visible_one("#custom-delay-min-input", Input).value = "8"
                app.query_visible_one("#custom-delay-max-input", Input).value = "13"
                await pilot.pause()
                self.assertEqual(app.task_manager.delay, "3")
                self.assertEqual(app.task_manager.current_delay_bounds(), (15, 30))
                await pilot.click("#save-polling")
                await pilot.pause()
                self.assertEqual(app.task_manager.delay, "custom")
                self.assertEqual(app.task_manager.current_delay_bounds(), (8, 13))

                await pilot.click("#tile-buy-delay")
                await pilot.pause()
                app.query_visible_one("#purchase-delay-min-input", Input).value = "4.5"
                app.query_visible_one("#purchase-delay-max-input", Input).value = "8"
                await pilot.pause()
                self.assertEqual(app.task_manager.purchase_delay_bounds, (1.0, 2.5))
                await pilot.click("#save-buy-delay")
                await pilot.pause()
                self.assertEqual(app.task_manager.purchase_delay_bounds, (4.5, 8.0))

                await pilot.click("#tile-spent")
                await pilot.pause()
                app.query_visible_one("#spend-cap-input", Input).value = "250"
                await pilot.pause()
                self.assertIsNone(app.task_manager.max_spend)
                await pilot.click("#save-spend-cap")
                await pilot.pause()
                self.assertEqual(app.task_manager.max_spend, 250)

    async def test_stats_page_uses_tiles_without_local_file_path(self):
        app = self.make_app()
        app.task_manager.session_detected_outfits = 5
        app.task_manager.session_successful_purchases = 4
        app.task_manager.session_silver_spent = 2_000_000_000
        app.task_manager.lifetime_successful_purchases = 9
        app.task_manager.lifetime_silver_spent = 12_000_000_000
        app.task_manager.reload_lifetime_stats = lambda: None

        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.press("3")
                self.assertIsInstance(app.query_one("#refresh-stats"), ModalAction)
                self.assertEqual(list(app.query("#stats-actions Button")), [])
                stat_tiles = [
                    app.query_one("#stats-session-detected", Static),
                    app.query_one("#stats-session-purchases", Static),
                    app.query_one("#stats-session-rate", Static),
                    app.query_one("#stats-session-spent", Static),
                    app.query_one("#stats-lifetime-purchases", Static),
                    app.query_one("#stats-lifetime-spent", Static),
                ]
                console = Console(width=100, color_system=None)
                with console.capture() as capture:
                    for tile in stat_tiles:
                        console.print(tile.content)
                rendered = capture.get()
                border_titles = "\n".join(str(tile.border_title) for tile in stat_tiles)
                await pilot.click("#refresh-stats")
                await pilot.pause()

        self.assertIn("Success Rate", border_titles)
        self.assertIn("80%", rendered)
        self.assertIn("2B silver", rendered)
        self.assertIn("12B silver", rendered)
        self.assertNotIn("Local Data File", rendered)
        self.assertEqual(app.status_message, "Stats refreshed.")

    async def test_marketplace_inventory_page_is_wip_and_uses_standard_action(self):
        app = self.make_app()
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.press("2")
                self.assertEqual(app.current_view, "wallet")
                self.assertIn(("wallet", "Inventory"), app.NAV_ITEMS)
                self.assertEqual(app.query_one("#screen-title", Static).content, "Marketplace Inventory")
                self.assertIn("WIP", str(app.query_one("#wallet-wip-note", Static).content))
                self.assertEqual(app.query_one("#wallet-wip-note", Static).styles.margin.top, 1)
                self.assertIsInstance(app.query_one("#refresh-wallet"), ModalAction)
                self.assertEqual(list(app.query("#wallet-actions Button")), [])

                await pilot.click("#refresh-wallet")
                await pilot.pause()

        self.assertIn("Inventory loaded", app.status_message)

    async def test_purchase_success_rate_uses_color_spectrum(self):
        app = self.make_app()
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(100, 36)):
                cases = [
                    (0, 0, "error"),
                    (1, 10, "error"),
                    (3, 10, "orange"),
                    (5, 10, "warning"),
                    (8, 10, "success"),
                ]

                for successful, detected, expected_level in cases:
                    app.task_manager.session_successful_purchases = successful
                    app.task_manager.session_detected_outfits = detected
                    self.assertEqual(app.purchase_rate_level(), expected_level)

                self.assertEqual(STATUS_STYLES["error"], "bold rgb(209,106,106)")
                self.assertEqual(STATUS_STYLES["success"], "bold rgb(126,184,138)")
                self.assertEqual(STATUS_STYLES["info"], "bold rgb(232,229,220)")

    async def test_sidebar_test_log_button_adds_dashboard_event(self):
        app = self.make_app(launch_mode="test")
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)), patch(
            "bdo_marketplace_tools.ui.app.random.choice",
            return_value=("Synthetic layout probe.", "success"),
        ):
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.press("3")
                self.assertEqual(app.current_view, "stats")

                await pilot.click("#add-test-log")
                self.assertEqual(app.current_view, "dashboard")
                self.assertTrue(any("Synthetic layout probe." in event for event in app.task_manager.events))

    async def test_dashboard_event_log_rehydrates_after_navigation(self):
        app = self.make_app()
        app.task_manager.add_event("Persistent event before navigation.", "success")
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(100, 36)) as pilot:
                event_text = "\n".join(line.text for line in app.query_one("#event-log").lines)
                self.assertIn("Persistent event before navigation.", event_text)

                await pilot.press("1")
                self.assertEqual(app.current_view, "settings")
                await pilot.press("escape")
                self.assertEqual(app.current_view, "dashboard")

                event_text = "\n".join(line.text for line in app.query_one("#event-log").lines)
                self.assertIn("Persistent event before navigation.", event_text)
                self.assertEqual(app._dashboard_snapshot, app.dashboard_snapshot())

    async def test_dashboard_event_log_switches_between_core_and_ui_streams(self):
        app = self.make_app()
        app.task_manager.add_event("Core monitor detail.", "success")
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(100, 36)) as pilot:
                app.set_status("UI setting saved.", "info")
                await pilot.pause()

                self.assertEqual(app.query_one("#event-log-toolbar-title", Static).content, "Event Log View:")
                self.assertEqual(app.query_one("#event-log-toolbar").styles.height.value, 1)
                self.assertIn("log-filter-selected", app.query_one("#log-filter-core").classes)
                self.assertEqual(app.query_one("#log-filter-core", Static).content, "Core logs")
                self.assertEqual(app.query_one("#log-filter-ui", Static).content, "UI logs")
                event_text = "\n".join(line.text for line in app.query_one("#event-log").lines)
                self.assertIn("Core monitor detail.", event_text)
                self.assertNotIn("UI setting saved.", event_text)

                await pilot.click("#log-filter-ui")
                await pilot.pause()

                self.assertEqual(app.event_log_mode, "ui")
                self.assertEqual(app.task_manager.event_log_view, "ui")
                self.assertIn("log-filter-selected", app.query_one("#log-filter-ui").classes)
                event_text = "\n".join(line.text for line in app.query_one("#event-log").lines)
                self.assertIn("UI setting saved.", event_text)
                self.assertNotIn("Core monitor detail.", event_text)

    async def test_debug_controls_are_test_mode_only(self):
        live_app = self.make_app()
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)):
            async with live_app.run_test(size=(100, 36)):
                self.assertEqual(list(live_app.query("#test-controls")), [])
                await live_app.add_test_log()
                self.assertTrue(any("Debug actions" in event for event in live_app.task_manager.events))
                self.assertIn("Debug actions", live_app.status_message)

        test_app = self.make_app(launch_mode="test")
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)):
            async with test_app.run_test(size=(100, 36)):
                self.assertEqual(len(list(test_app.query("#test-controls"))), 1)
                self.assertEqual(len(list(test_app.query("#toggle-test-session"))), 1)
                self.assertEqual(len(list(test_app.query("#toggle-auto-reauth"))), 1)
                self.assertEqual(len(list(test_app.query("#expire-test-session"))), 1)
                self.assertEqual(len(list(test_app.query("#run-reauth-check"))), 1)
                self.assertEqual(len(list(test_app.query("#open-blank-browser"))), 1)
                self.assertEqual(len(list(test_app.query("#start-test-monitor"))), 1)
                self.assertEqual(len(list(test_app.query("#start-test-buy"))), 1)
                self.assertEqual(len(list(test_app.query("#stop-test-monitor"))), 1)
                self.assertEqual(len(list(test_app.query("#fake-detection"))), 1)
                self.assertEqual(len(list(test_app.query("#fake-buy-success"))), 1)

    async def test_reauthentication_debug_buttons_call_test_hooks(self):
        app = self.make_app(launch_mode="test")
        app.task_manager.debug_toggle_steam_auto_reauth = Mock(return_value=True)
        app.task_manager.debug_invalidate_marketplace_session = Mock(return_value=True)
        app.task_manager.debug_run_reauthentication_check = AsyncMock(return_value=True)

        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(100, 36)) as pilot:
                self.assertIn("Auto Reauth", str(app.query_one("#toggle-auto-reauth", Button).render()))
                self.assertIn("Reauth Check", str(app.query_one("#run-reauth-check", Button).render()))

                await pilot.click("#toggle-auto-reauth")
                await pilot.pause(0.1)

                app.task_manager.debug_toggle_steam_auto_reauth.assert_called_once()
                self.assertIn("automatic re-authentication enabled", app.status_message)

                previous_status = app.status_message
                await pilot.click("#expire-test-session")
                await pilot.pause(0.1)

                app.task_manager.debug_invalidate_marketplace_session.assert_called_once()
                self.assertEqual(app.status_message, previous_status)

                await pilot.click("#run-reauth-check")
                await pilot.pause(0.1)

                app.task_manager.debug_run_reauthentication_check.assert_awaited_once()
                self.assertIn("re-authentication check succeeded", app.status_message)

    async def test_blank_browser_debug_button_starts_worker(self):
        app = self.make_app(launch_mode="test")
        app.task_manager.debug_open_blank_browser_diagnostic = AsyncMock(return_value=True)

        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(100, 36)) as pilot:
                self.assertIn("Blank Browser", str(app.query_one("#open-blank-browser", Button).render()))

                await pilot.click("#open-blank-browser")
                await pilot.pause(0.2)

                app.task_manager.debug_open_blank_browser_diagnostic.assert_awaited_once()
                self.assertIn("Blank Chrome diagnostic browser closed", app.status_message)

    async def test_single_item_test_monitor_sidebar_controls_use_separate_task(self):
        app = self.make_app(launch_mode="test")
        app.api_handler.login_status = True

        async def idle_test_checker():
            await asyncio.sleep(60)

        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)), patch.object(
            app.task_manager,
            "single_item_test_checker",
            new=idle_test_checker,
        ):
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.click("#start-test-monitor")
                await pilot.pause(0.1)

                self.assertTrue(app.task_manager.single_item_test_checker_enabled)
                self.assertFalse(app.task_manager.checker_enabled)
                self.assertIn("Single-item test monitor started", app.status_message)
                self.assertTrue(any("buy calls are disabled" in event for event in app.task_manager.events))
                self.assertFalse(app.task_manager.single_item_test_purchase_enabled)

                await app.start_monitor()
                self.assertFalse(app.task_manager.checker_enabled)
                self.assertIn("Stop it before starting the normal monitor", app.status_message)

                await pilot.click("#stop-test-monitor")
                await pilot.pause(0.1)
                self.assertFalse(app.task_manager.single_item_test_checker_enabled)
                self.assertIn("Single-item test monitor stopped", app.status_message)

    async def test_single_item_test_buy_requires_login_and_confirmation(self):
        app = self.make_app(launch_mode="test")
        app.task_manager.set_purchase_delay_range("3.25", "5.5")

        async def idle_test_checker():
            await asyncio.sleep(60)

        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)), patch.object(
            app.task_manager,
            "single_item_test_checker",
            new=idle_test_checker,
        ):
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.click("#start-test-buy")
                await pilot.pause()
                self.assertFalse(app.task_manager.single_item_test_checker_enabled)
                self.assertIn("Login required", app.status_message)

                app.api_handler.login_status = True
                app.api_handler.email = "user@example.com"
                await pilot.click("#start-test-buy")
                await pilot.pause(0.1)
                self.assertFalse(app.task_manager.single_item_test_checker_enabled)
                self.assertIsInstance(app.query_visible_one("#confirm-start"), ModalAction)
                confirmation_text = "\n".join(
                    str(widget.render()) for widget in app.screen_stack[-1].query(Static)
                )
                self.assertIn("Buy delay: 3.25-5.5s", confirmation_text)

                await pilot.click("#confirm-start")
                await pilot.pause(0.1)
                self.assertTrue(app.task_manager.single_item_test_checker_enabled)
                self.assertTrue(app.task_manager.single_item_test_purchase_enabled)
                self.assertIn("Single-item buy test started", app.status_message)

                await app.task_manager.stop_single_item_test_checker()

    async def test_polling_modal_saves_preset_equivalent_range_as_preset(self):
        app = self.make_app()
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.click("#tile-polling")
                await pilot.pause()
                await pilot.click("#polling-preset-2")
                await pilot.pause()
                await pilot.click("#save-polling")
                await pilot.pause()

        self.assertEqual(app.task_manager.delay, "2")
        self.assertEqual(app.task_manager.current_delay_bounds(), (5, 10))
        self.assertIn("Balanced (5-10s)", app.status_message)

    async def test_buy_mode_start_requires_login_logs_one_combined_warning(self):
        app = self.make_app()
        app.task_manager.purchase_submission_enabled = True
        app.api_handler.login_status = False

        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(100, 36)):
                await app.start_monitor()

        self.assertFalse(app.task_manager.checker_enabled)
        self.assertEqual(len(app.task_manager.events), 1)
        event_text = app.task_manager.events[0]
        self.assertIn("Login required before starting buy mode", event_text)
        self.assertIn("Login or refresh the marketplace session", event_text)

    async def test_login_refresh_logs_only_final_login_result(self):
        app = self.make_app()
        app.api_handler.email = "user@example.com"
        app.api_handler.password = "secret"
        app.api_handler.is_session_expired = AsyncMock(return_value=-1)
        app.api_handler.login = AsyncMock(return_value=0)

        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=("user@example.com", "secret")):
            async with app.run_test(size=(100, 36)):
                await app.login_refresh()

        event_text = "\n".join(app.task_manager.events)
        self.assertEqual(len(app.task_manager.events), 2)
        self.assertIn("Fetching session status", event_text)
        self.assertIn("Login failed.", event_text)
        self.assertNotIn("Checking marketplace session", event_text)
        self.assertNotIn("Login check complete", event_text)

    async def test_fake_detection_button_does_not_buy(self):
        app = self.make_app(launch_mode="test")
        app.task_manager.purchase_submission_enabled = True
        app.task_manager.buy_item = AsyncMock()
        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.click("#fake-detection")

        app.task_manager.buy_item.assert_not_called()
        self.assertEqual(app.task_manager.session_detected_outfits, 1)
        self.assertEqual(app.task_manager.session_successful_purchases, 0)

    async def test_fake_buy_success_button_updates_metrics_and_saves(self):
        app = self.make_app(launch_mode="test")
        with patch.object(app.task_manager, "save_local_data") as save_mock, patch(
            "bdo_marketplace_tools.ui.app.load_credentials",
            return_value=(None, None),
        ):
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.click("#fake-buy-success")

        self.assertEqual(app.task_manager.session_detected_outfits, 1)
        self.assertEqual(app.task_manager.session_successful_purchases, 1)
        self.assertGreater(app.task_manager.session_silver_spent, 0)
        save_mock.assert_called_once()

    async def test_test_session_toggle_allows_buy_mode_without_live_purchase_api(self):
        app = self.make_app(launch_mode="test")
        app.task_manager.purchase_submission_enabled = True
        app.api_handler.buy_item = AsyncMock()

        async def idle_checker():
            await asyncio.sleep(60)

        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)), patch.object(
            app.task_manager,
            "checker",
            new=idle_checker,
        ), patch.object(app.task_manager, "save_local_data"):
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.click("#toggle-test-session")
                await pilot.pause()
                self.assertTrue(app.task_manager.simulated_session_enabled)
                self.assertTrue(app.api_handler.login_status)
                self.assertIn("Test session marked valid", app.status_message)

                await app.start_monitor()
                await pilot.pause(0.1)
                self.assertFalse(app.task_manager.checker_enabled)
                self.assertIsInstance(app.query_visible_one("#confirm-start"), ModalAction)

                await pilot.click("#confirm-start")
                await pilot.pause(0.1)
                self.assertTrue(app.task_manager.checker_enabled)
                self.assertTrue(app.task_manager.purchase_submission_enabled)

                await app.task_manager.buy_item([["debug-premium-outfit", "1", "2020000000"]])
                app.api_handler.buy_item.assert_not_called()
                self.assertEqual(app.task_manager.session_successful_purchases, 1)

                await pilot.click("#toggle-test-session")
                await pilot.pause()
                self.assertFalse(app.task_manager.simulated_session_enabled)
                self.assertFalse(app.api_handler.login_status)
                self.assertFalse(app.task_manager.purchase_submission_enabled)

    async def test_watch_only_start_works_logged_out_and_buy_mode_blocks(self):
        app = self.make_app()

        async def idle_checker():
            await asyncio.sleep(60)

        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)), patch.object(
            app.task_manager,
            "checker",
            new=idle_checker,
        ):
            async with app.run_test(size=(100, 36)):
                await app.start_monitor()
                self.assertTrue(app.task_manager.checker_enabled)
                await app.task_manager.stop_checker()

                app.task_manager.purchase_submission_enabled = True
                app.api_handler.login_status = False
                await app.start_monitor()
                self.assertFalse(app.task_manager.checker_enabled)
                self.assertIn("Login or refresh", app.status_message)

    async def test_repeated_start_and_stop_controls_log_without_duplicate_monitor_tasks(self):
        app = self.make_app()

        async def idle_checker():
            await asyncio.sleep(60)

        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)), patch.object(
            app.task_manager,
            "checker",
            new=idle_checker,
        ):
            async with app.run_test(size=(100, 36)):
                await app.stop_monitor()
                self.assertIn("already stopped", app.status_message)

                await app.start_monitor()
                first_task = app.task_manager.checker_task
                self.assertTrue(app.task_manager.checker_enabled)

                await app.start_monitor()
                self.assertIs(app.task_manager.checker_task, first_task)
                self.assertIn("already running", app.status_message)
                self.assertTrue(any("no additional monitor task started" in event for event in app.task_manager.events))

                await app.stop_monitor()
                self.assertFalse(app.task_manager.checker_enabled)

    async def test_monitor_modal_buttons_follow_running_state_and_watch_start_closes_modal(self):
        app = self.make_app()

        async def idle_checker():
            await asyncio.sleep(60)

        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=(None, None)), patch.object(
            app.task_manager,
            "checker",
            new=idle_checker,
        ):
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.click("#tile-monitor")
                await pilot.pause()
                self.assertFalse(app.query_visible_one("#modal-start-monitor", Button).disabled)
                self.assertTrue(app.query_visible_one("#modal-stop-monitor", Button).disabled)

                await pilot.click("#modal-start-monitor")
                await pilot.pause(0.1)
                self.assertTrue(app.task_manager.checker_enabled)
                self.assertEqual([type(screen).__name__ for screen in app.screen_stack], ["Screen"])

                await pilot.click("#tile-monitor")
                await pilot.pause()
                self.assertTrue(app.query_visible_one("#modal-start-monitor", Button).disabled)
                self.assertFalse(app.query_visible_one("#modal-stop-monitor", Button).disabled)

                await app.stop_monitor()

    async def test_buy_mode_start_confirmation_closes_monitor_modal_stack(self):
        app = self.make_app()
        app.api_handler.login_status = True
        app.api_handler.email = "user@example.com"
        app.task_manager.purchase_submission_enabled = True
        app.task_manager.set_purchase_delay_range("4.5", "8")

        async def idle_checker():
            await asyncio.sleep(60)

        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=("user@example.com", "secret")), patch.object(
            app.task_manager,
            "checker",
            new=idle_checker,
        ):
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.click("#tile-monitor")
                await pilot.pause()
                await pilot.click("#modal-start-monitor")
                await pilot.pause(0.1)
                self.assertEqual(type(app.screen_stack[-1]).__name__, "ConfirmBuyModeScreen")
                confirmation_text = "\n".join(
                    str(widget.render()) for widget in app.screen_stack[-1].query(Static)
                )
                self.assertIn("Buy delay: 4.5-8s", confirmation_text)

                await pilot.click("#confirm-start")
                await pilot.pause(0.1)
                self.assertTrue(app.task_manager.checker_enabled)
                self.assertEqual([type(screen).__name__ for screen in app.screen_stack], ["Screen"])

                await app.stop_monitor()

    async def test_running_watch_monitor_requires_confirmation_before_buy_mode(self):
        app = self.make_app()
        app.api_handler.login_status = True
        app.api_handler.email = "user@example.com"

        async def idle_checker():
            await asyncio.sleep(60)

        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=("user@example.com", "secret")), patch.object(
            app.task_manager,
            "checker",
            new=idle_checker,
        ):
            async with app.run_test(size=(100, 36)) as pilot:
                await app.start_monitor()
                first_task = app.task_manager.checker_task
                self.assertTrue(app.task_manager.checker_enabled)
                self.assertFalse(app.task_manager.purchase_submission_enabled)

                await app.apply_purchase_mode(True)
                await pilot.pause(0.1)
                self.assertFalse(app.task_manager.purchase_submission_enabled)
                self.assertIs(app.task_manager.checker_task, first_task)
                self.assertIsInstance(app.query_visible_one("#confirm-start"), ModalAction)

                await pilot.click("#confirm-start")
                await pilot.pause(0.1)
                self.assertTrue(app.task_manager.purchase_submission_enabled)
                self.assertIs(app.task_manager.checker_task, first_task)
                self.assertIn("Buy mode enabled", app.status_message)

                await app.stop_monitor()

    async def test_buy_mode_requires_confirmation_before_starting(self):
        app = self.make_app()
        app.api_handler.login_status = True
        app.api_handler.email = "user@example.com"
        app.task_manager.purchase_submission_enabled = True

        async def idle_checker():
            await asyncio.sleep(60)

        with patch("bdo_marketplace_tools.ui.app.load_credentials", return_value=("user@example.com", "secret")), patch.object(
            app.task_manager,
            "checker",
            new=idle_checker,
        ):
            async with app.run_test(size=(100, 36)) as pilot:
                await app.start_monitor()
                await pilot.pause(0.1)
                self.assertFalse(app.task_manager.checker_enabled)
                self.assertIsInstance(app.query_visible_one("#confirm-start"), ModalAction)
                self.assertIn("modal-action-tile", app.query_visible_one("#confirm-start", ModalAction).classes)
                await pilot.click("#confirm-start")
                await pilot.pause(0.1)
                self.assertTrue(app.task_manager.checker_enabled)


if __name__ == "__main__":
    unittest.main()
