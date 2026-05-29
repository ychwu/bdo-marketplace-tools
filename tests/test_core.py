import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import main as app_main
from textual.color import Color
from textual.widgets import Input
from market.api_handler import APIHandler, MarketplaceAPIError, MarketplaceResponseError, purchase_result_message
from market.pricing import apply_price_rules, purchase_record_count, purchase_record_spend
from resources.task_manager import BackgroundTasks
from resources.textual_ui import BANNER_ART, DEFAULT_THEME, STATUS_STYLES, DashboardTile, MarketplaceToolsApp


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
        self.assertIn("price mismatch", purchase_result_message(-14, "item", "100"))
        self.assertIn("duplicate pre-order", purchase_result_message(34, "item", "100"))
        self.assertIn("resultCode 999", purchase_result_message(999, "item", "100"))

    def test_purchase_result_code_validation(self):
        handler = object.__new__(APIHandler)

        self.assertEqual(APIHandler._purchase_result_code(handler, {"resultCode": "-14"}), -14)
        with self.assertRaises(MarketplaceResponseError):
            APIHandler._purchase_result_code(handler, {})


class APIBuyFlowTests(unittest.IsolatedAsyncioTestCase):
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

        with patch("market.api_handler.asyncio.sleep", new=AsyncMock()):
            summary = await APIHandler.buy_item(handler, [["item", "2", "100"]])

        self.assertEqual(summary["attempted"], 2)
        self.assertEqual(summary["purchased"], 2)
        self.assertEqual(
            summary["purchase_records"],
            [
                {"item_id": "item", "price": 100, "count": 1, "result_code": 0},
                {"item_id": "item", "price": 100, "count": 1, "result_code": 0},
            ],
        )


class BackgroundTaskTests(unittest.IsolatedAsyncioTestCase):
    def make_task_manager(self):
        with patch("resources.task_manager._load_local_data", return_value=LOCAL_DATA.copy()):
            return BackgroundTasks(FakeAPI())

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

    async def test_fake_detection_uses_watch_only_path(self):
        manager = self.make_task_manager()
        manager.purchase_submission_enabled = True
        manager.buy_item = AsyncMock()

        await manager.debug_fake_outfit_detection()

        manager.buy_item.assert_not_called()
        self.assertEqual(manager.session_detected_outfits, 1)
        self.assertEqual(manager.session_successful_purchases, 0)
        self.assertTrue(any("Outfit detected: 1" in event for event in manager.events))

    async def test_fake_purchase_updates_success_rate_and_local_totals(self):
        manager = self.make_task_manager()
        with patch.object(manager, "save_local_data") as save_mock:
            await manager.debug_simulate_purchase_success()

        self.assertEqual(manager.session_detected_outfits, 1)
        self.assertEqual(manager.session_successful_purchases, 1)
        self.assertEqual(manager.lifetime_successful_purchases, 1)
        self.assertGreater(manager.session_silver_spent, 0)
        save_mock.assert_called_once()

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
                self.assertEqual(app.query_one("#banner").render(), BANNER_ART)
                self.assertTrue(app.query_one("#banner").display)
                self.assertFalse(app.query_one("#screen-title").display)
                await pilot.press("1")
                self.assertEqual(app.current_view, "settings")
                self.assertFalse(app.query_one("#banner").display)
                self.assertTrue(app.query_one("#screen-title").display)
                await pilot.press("3")
                self.assertEqual(app.current_view, "stats")
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

    async def test_dashboard_live_metrics_refresh(self):
        app = self.make_app()
        with patch("resources.textual_ui.load_credentials", return_value=(None, None)):
            async with app.run_test(size=(100, 36)) as pilot:
                app.task_manager.session_detected_outfits = 4
                app.task_manager.session_successful_purchases = 2
                app.task_manager.session_silver_spent = 1_500_000_000
                app.refresh_live_widgets()

                rendered_tiles = []
                for tile_id in ("monitor", "spent", "credentials", "session", "polling", "success", "runtime"):
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
                self.assertIn("Runtime", rendered_tiles)
                self.assertIn("No account", rendered_tiles)
                self.assertIn("Marketplace auth", rendered_tiles)
                self.assertIn("15-30s", rendered_tiles)
                self.assertIn("Slow", rendered_tiles)
                self.assertIn("2/4 bought", rendered_tiles)
                self.assertIn("50%", rendered_tiles)
                self.assertIn("1.5B silver", rendered_tiles)

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
                self.assertEqual(app.query_visible_one("#delay-select").value, app.task_manager.delay)
                self.assertEqual(len(list(app.screen_stack[-1].query("#polling-summary"))), 1)
                self.assertEqual(len(list(app.screen_stack[-1].query("#settings-summary"))), 0)
                await pilot.click("#save-polling")
                await pilot.pause()
                self.assertEqual([type(screen).__name__ for screen in app.screen_stack], ["Screen"])
                await pilot.click("#tile-polling")
                await pilot.pause()
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
                self.assertEqual(len(list(test_app.query("#fake-detection"))), 1)
                self.assertEqual(len(list(test_app.query("#fake-buy-success"))), 1)

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
        self.assertEqual(len(app.task_manager.events), 1)
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
                await pilot.click("#confirm-start")
                await pilot.pause(0.1)
                self.assertTrue(app.task_manager.checker_enabled)


if __name__ == "__main__":
    unittest.main()
