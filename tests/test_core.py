import asyncio
import json
import requests
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import main as app_main
from rich.console import Console
from textual.color import Color
from textual.widgets import Button, Input, Static
from market.api_handler import (
    APIHandler,
    DEFAULT_PURCHASE_DELAY_BOUNDS,
    MARKET_AJAX_HEADER,
    MarketplaceAPIError,
    MarketplaceResponseError,
    marketplace_silver_balance,
    purchase_result_message,
)
from market.pricing import apply_price_rules, purchase_record_count, purchase_record_spend
from market.test_mode import SINGLE_ITEM_TEST_TARGET, check_single_item_stock, parse_single_item_stock_response
from resources import credentials as credentials_module
from resources import task_manager as task_manager_module
from resources.task_manager import BackgroundTasks
from resources.textual_ui import BANNER_ART, DEFAULT_THEME, STATUS_STYLES, DashboardTile, MarketplaceToolsApp, ModalAction


LOCAL_DATA = {
    "successful_purchases": 0,
    "silver_spent": 0,
}


class FakeAPI:
    login_status = False
    email = None
    password = None

    async def get_mp_inventory(self):
        return {"wallet": [{"currency": "silver", "amount": 123}]}

    async def check_stock(self):
        return []

    def save_session(self):
        pass


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
        with patch("resources.task_manager._load_local_data", return_value=LOCAL_DATA.copy()):
            fake_manager = BackgroundTasks(fake_api)
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
        with patch("resources.task_manager._load_local_data", return_value=LOCAL_DATA.copy()):
            fake_manager = BackgroundTasks(fake_api)
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
                ["unknown", "2", "12345"],
            ]
        )

        self.assertEqual(adjusted, [["premium", "1", "2170000000"], ["unknown", "2", "1180000000"]])
        self.assertEqual(
            fallbacks,
            [{"item_id": "unknown", "detected_price": "12345", "adjusted_price": "1180000000"}],
        )

    def test_purchase_record_helpers_sum_actual_successes(self):
        records = [
            {"item_id": "a", "price": 100, "count": 2},
            {"item_id": "b", "price": 250, "count": 1},
        ]

        self.assertEqual(purchase_record_count(records), 3)
        self.assertEqual(purchase_record_spend(records), 450)


class APIResultTests(unittest.TestCase):
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
            session_path = Path(temp_dir) / "resources" / "session.json"
            handler = object.__new__(APIHandler)

            with patch("market.api_handler.SESSION_COOKIE_PATH", session_path), patch(
                "market.api_handler.LEGACY_SESSION_PATHS",
                (),
            ):
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
    def test_missing_credentials_file_is_initialized_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            info_path = Path(temp_dir) / "resources" / "info.json"

            with patch("resources.credentials.INFO_PATH", info_path):
                self.assertEqual(credentials_module.load_credentials(), (None, None))

            self.assertTrue(info_path.exists())
            self.assertEqual(json.loads(info_path.read_text(encoding="utf-8")), {})

    def test_missing_local_data_file_is_initialized_with_default_totals(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_data_path = Path(temp_dir) / "resources" / "local_data.json"

            with patch("resources.task_manager.LOCAL_DATA_PATH", local_data_path):
                data = task_manager_module._load_local_data()

            self.assertEqual(data, LOCAL_DATA)
            self.assertTrue(local_data_path.exists())
            payload = json.loads(local_data_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, LOCAL_DATA)
            self.assertNotIn("updated_at", payload)


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
        with patch("market.api_handler.asyncio.sleep", new=sleep_mock):
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

        with patch("market.api_handler.random.uniform", return_value=4.5) as uniform_mock:
            with patch("market.api_handler.asyncio.sleep", new=AsyncMock()) as sleep_mock:
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

        with patch("market.api_handler.asyncio.sleep", new=AsyncMock()):
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


class BackgroundTaskTests(unittest.IsolatedAsyncioTestCase):
    def make_task_manager(self, test_mode_enabled=False):
        with patch("resources.task_manager._load_local_data", return_value=LOCAL_DATA.copy()):
            return BackgroundTasks(FakeAPI(), test_mode_enabled=test_mode_enabled)

    async def test_spend_cap_limits_items_by_price_order(self):
        manager = self.make_task_manager()
        manager.max_spend = 250

        capped = manager._apply_spend_cap([["a", "3", "100"], ["b", "2", "80"]])

        self.assertEqual(capped, [["a", "2", "100"]])

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

        with patch("resources.task_manager.check_single_item_stock", stock_check), patch(
            "resources.task_manager.random.uniform",
            return_value=3,
        ), patch(
            "resources.task_manager.asyncio.sleep",
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

        with patch("resources.task_manager.check_single_item_stock", stock_check), patch.object(
            manager,
            "save_local_data",
        ) as save_mock, patch(
            "resources.task_manager.random.uniform",
            return_value=3,
        ), patch(
            "resources.task_manager.asyncio.sleep",
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
        with patch("resources.task_manager.random.uniform", return_value=9) as uniform_mock:
            with patch("resources.task_manager.asyncio.sleep", new=AsyncMock(side_effect=asyncio.CancelledError)):
                with self.assertRaises(asyncio.CancelledError):
                    await manager.checker()

        uniform_mock.assert_called_once_with(8, 13)

    async def test_monitor_errors_back_off_from_normal_polling_window(self):
        manager = self.make_task_manager()
        manager.set_custom_delay_range(5, 10)
        manager.consecutive_cycle_errors = 2

        with patch("resources.task_manager.random.uniform", return_value=20) as uniform_mock:
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

        with patch("resources.task_manager.asyncio.sleep", new=AsyncMock(side_effect=asyncio.CancelledError)):
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

    async def test_login_status_checker_combines_expired_session_with_reauth_result(self):
        manager = self.make_task_manager()
        manager.api_handler.is_session_expired = AsyncMock(return_value=-1)
        manager.api_handler.login = AsyncMock(return_value=0)

        with patch("resources.task_manager.asyncio.sleep", new=AsyncMock(return_value=None)):
            await manager.login_status_checker()

        self.assertEqual(len(manager.events), 1)
        self.assertIn("Session expired. Re-authentication failed.", manager.events[0])


class TextualAppTests(unittest.IsolatedAsyncioTestCase):
    def make_app(self, launch_mode="live"):
        with patch("resources.task_manager._load_local_data", return_value=LOCAL_DATA.copy()):
            manager = BackgroundTasks(FakeAPI())
        return MarketplaceToolsApp(manager, manager.api_handler, launch_mode=launch_mode)

    async def test_app_launches_and_navigates_sidebar(self):
        app = self.make_app()
        with patch("resources.textual_ui.load_credentials", return_value=(None, None)):
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
                await pilot.press("3")
                self.assertEqual(app.current_view, "stats")
                self.assertEqual(len(list(app.query("#stats-output"))), 0)
                self.assertEqual(len(list(app.query(".stats-tile"))), 6)
                await pilot.press("escape")
                self.assertEqual(app.current_view, "dashboard")
                self.assertTrue(app.query_one("#banner").display)

    async def test_dashboard_banner_shows_when_terminal_is_large_enough(self):
        app = self.make_app()
        with patch("resources.textual_ui.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(150, 45)):
                self.assertEqual(app.current_view, "dashboard")
                self.assertTrue(app.query_one("#banner").display)

    async def test_dashboard_content_remains_scrollable(self):
        app = self.make_app()
        with patch("resources.textual_ui.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(100, 36)):
                self.assertEqual(app.current_view, "dashboard")
                self.assertEqual(app.query_one("#content").styles.overflow_y, "auto")
                self.assertGreaterEqual(app.query_one("#event-log").size.height, 6)
                self.assertLessEqual(app.query_one("#sidebar").region.width, 23)
                self.assertEqual(app.query_one("#event-log").styles.border_title_color, Color(255, 145, 60))

    async def test_credentials_validation_and_password_masking(self):
        app = self.make_app()
        with patch("resources.textual_ui.load_credentials", return_value=(None, None)), patch(
            "resources.textual_ui.save_credentials"
        ) as save_mock:
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.click("#tile-credentials")
                await pilot.pause()
                password_input = app.query_visible_one("#password-input")
                self.assertTrue(password_input.password)

                await pilot.click("#save-credentials")
                self.assertIn("Email field cannot be empty", app.status_message)

                app.query_visible_one("#email-input").value = "user@example.com"
                app.query_visible_one("#password-input").value = "secret"
                await pilot.click("#save-credentials")
                save_mock.assert_called_once_with("user@example.com", "secret")
                self.assertIn("Credentials saved", app.status_message)
                self.assertEqual([type(screen).__name__ for screen in app.screen_stack], ["Screen"])

    async def test_saved_credentials_are_labeled_set_not_authenticated_ready(self):
        app = self.make_app()
        with patch("resources.textual_ui.load_credentials", return_value=("user@example.com", "secret")):
            async with app.run_test(size=(100, 36)):
                credential_status, credential_detail, credential_level, _, _ = app.credential_state()

        self.assertEqual(credential_status, "Set")
        self.assertEqual(credential_detail, "us**@example.com")
        self.assertEqual(credential_level, "success")

    async def test_dashboard_live_metrics_refresh(self):
        app = self.make_app()
        with patch("resources.textual_ui.load_credentials", return_value=(None, None)):
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
                self.assertTrue(app.query_visible_one("#password-input", Input).password)
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

    async def test_buy_delay_modal_saves_valid_decimals_and_keeps_invalid_open(self):
        app = self.make_app()
        with patch("resources.textual_ui.load_credentials", return_value=(None, None)):
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

    async def test_stats_page_uses_tiles_without_local_file_path(self):
        app = self.make_app()
        app.task_manager.session_detected_outfits = 5
        app.task_manager.session_successful_purchases = 4
        app.task_manager.session_silver_spent = 2_000_000_000
        app.task_manager.lifetime_successful_purchases = 9
        app.task_manager.lifetime_silver_spent = 12_000_000_000
        app.task_manager.reload_lifetime_stats = lambda: None

        with patch("resources.textual_ui.load_credentials", return_value=(None, None)):
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

    async def test_purchase_success_rate_uses_color_spectrum(self):
        app = self.make_app()
        with patch("resources.textual_ui.load_credentials", return_value=(None, None)):
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
        with patch("resources.textual_ui.load_credentials", return_value=(None, None)), patch(
            "resources.textual_ui.random.choice",
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
        with patch("resources.textual_ui.load_credentials", return_value=(None, None)):
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

    async def test_debug_controls_are_test_mode_only(self):
        live_app = self.make_app()
        with patch("resources.textual_ui.load_credentials", return_value=(None, None)):
            async with live_app.run_test(size=(100, 36)):
                self.assertEqual(list(live_app.query("#test-controls")), [])
                await live_app.add_test_log()
                self.assertTrue(any("Debug actions" in event for event in live_app.task_manager.events))
                self.assertIn("Debug actions", live_app.status_message)

        test_app = self.make_app(launch_mode="test")
        with patch("resources.textual_ui.load_credentials", return_value=(None, None)):
            async with test_app.run_test(size=(100, 36)):
                self.assertEqual(len(list(test_app.query("#test-controls"))), 1)
                self.assertEqual(len(list(test_app.query("#toggle-test-session"))), 1)
                self.assertEqual(len(list(test_app.query("#start-test-monitor"))), 1)
                self.assertEqual(len(list(test_app.query("#start-test-buy"))), 1)
                self.assertEqual(len(list(test_app.query("#stop-test-monitor"))), 1)
                self.assertEqual(len(list(test_app.query("#fake-detection"))), 1)
                self.assertEqual(len(list(test_app.query("#fake-buy-success"))), 1)

    async def test_single_item_test_monitor_sidebar_controls_use_separate_task(self):
        app = self.make_app(launch_mode="test")
        app.api_handler.login_status = True

        async def idle_test_checker():
            await asyncio.sleep(60)

        with patch("resources.textual_ui.load_credentials", return_value=(None, None)), patch.object(
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

        with patch("resources.textual_ui.load_credentials", return_value=(None, None)), patch.object(
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
        with patch("resources.textual_ui.load_credentials", return_value=(None, None)):
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

        with patch("resources.textual_ui.load_credentials", return_value=(None, None)):
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

        with patch("resources.textual_ui.load_credentials", return_value=("user@example.com", "secret")):
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
        with patch("resources.textual_ui.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.click("#fake-detection")

        app.task_manager.buy_item.assert_not_called()
        self.assertEqual(app.task_manager.session_detected_outfits, 1)
        self.assertEqual(app.task_manager.session_successful_purchases, 0)

    async def test_fake_buy_success_button_updates_metrics_and_saves(self):
        app = self.make_app(launch_mode="test")
        with patch.object(app.task_manager, "save_local_data") as save_mock, patch(
            "resources.textual_ui.load_credentials",
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

        with patch("resources.textual_ui.load_credentials", return_value=(None, None)), patch.object(
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

        with patch("resources.textual_ui.load_credentials", return_value=(None, None)), patch.object(
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

        with patch("resources.textual_ui.load_credentials", return_value=(None, None)), patch.object(
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

        with patch("resources.textual_ui.load_credentials", return_value=(None, None)), patch.object(
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

        with patch("resources.textual_ui.load_credentials", return_value=("user@example.com", "secret")), patch.object(
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

        with patch("resources.textual_ui.load_credentials", return_value=("user@example.com", "secret")), patch.object(
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

        with patch("resources.textual_ui.load_credentials", return_value=("user@example.com", "secret")), patch.object(
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
