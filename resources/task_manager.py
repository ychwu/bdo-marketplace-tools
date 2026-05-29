import asyncio
import json
import random
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from market.api_handler import MarketplaceAPIError
from market.pricing import apply_price_rules, purchase_record_count, purchase_record_spend
from resources.display import EVENT_LEVEL_COLORS, format_duration

LOCAL_DATA_PATH = Path(__file__).with_name("local_data.json")
DEFAULT_LOCAL_DATA = {
    "successful_purchases": 0,
    "silver_spent": 0,
}
DEBUG_OUTFIT_LISTING = [["debug-premium-outfit", "1", "2020000000"]]


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _load_local_data():
    try:
        with LOCAL_DATA_PATH.open("r", encoding="utf-8") as data_file:
            data = json.load(data_file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return DEFAULT_LOCAL_DATA.copy()

    return {
        "successful_purchases": _safe_int(data.get("successful_purchases")),
        "silver_spent": _safe_int(data.get("silver_spent")),
    }


def _save_local_data(data):
    payload = DEFAULT_LOCAL_DATA.copy()
    payload.update(data)
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    LOCAL_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCAL_DATA_PATH.open("w", encoding="utf-8") as data_file:
        json.dump(payload, data_file, indent=2)
        data_file.write("\n")


class BackgroundTasks:
    def __init__(self, api_handler):
        local_data = _load_local_data()
        self.api_handler = api_handler
        self.checker_task = None
        self.login_checker_task = None
        self.checker_enabled = False
        self.delay_choices = {
            "1": ("Fast", (3, 5)),
            "2": ("Balanced", (5, 10)),
            "3": ("Slow", (15, 30)),
        }
        self.delay = "3"
        self.custom_delay_range = (15, 30)
        self.events = deque(maxlen=9)
        self.purchase_submission_enabled = False
        self.max_spend = None
        self.checker_started_at = None
        self.session_detected_outfits = 0
        self.session_successful_purchases = 0
        self.session_silver_spent = 0
        self.lifetime_successful_purchases = local_data["successful_purchases"]
        self.lifetime_silver_spent = local_data["silver_spent"]

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

    def add_event(self, message, level="info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        style = EVENT_LEVEL_COLORS.get(level, EVENT_LEVEL_COLORS["info"])
        self.events.append(f"[dim]{timestamp}[/dim] [{style}]{message}[/{style}]")

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

    def runtime_label(self):
        if not self.checker_enabled or self.checker_started_at is None:
            return "00:00:00"
        return format_duration(time.monotonic() - self.checker_started_at)

    async def start_checker(self):
        if self.purchase_submission_enabled and not self.api_handler.login_status:
            return

        if self.checker_task is None or self.checker_task.done():
            self.checker_started_at = time.monotonic()
            self.checker_task = asyncio.create_task(self.checker())
            self.checker_task.add_done_callback(self._handle_checker_done)
            self.checker_enabled = True

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
        self.checker_started_at = None
        if self.checker_task is task:
            self.checker_task = None

    async def stop_checker(self):
        if self.checker_task and not self.checker_task.done():
            self.checker_task.cancel()
            try:
                await self.checker_task
            except asyncio.CancelledError:
                pass

        self.checker_enabled = False
        self.checker_started_at = None
        self.checker_task = None

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
            while True:
                try:
                    buy_list = await self.api_handler.check_stock()
                    await self.process_detected_outfits(buy_list)
                except Exception as exc:
                    self.add_event(f"Monitor cycle failed: {exc}", "error")

                sleep_duration = random.uniform(*self.current_delay_bounds())
                await asyncio.sleep(sleep_duration)
        except asyncio.CancelledError:
            raise

    async def process_detected_outfits(self, buy_list, allow_purchase=None):
        if not buy_list:
            return

        detected_count = self._detected_outfit_count(buy_list)
        self.session_detected_outfits += detected_count
        purchase_enabled = self.purchase_submission_enabled if allow_purchase is None else allow_purchase

        if purchase_enabled:
            self.add_event(f"Outfit detected: {detected_count} available outfits. Attempting purchase.", "success")
            await self.buy_item(buy_list)
        else:
            self.add_event(f"Outfit detected: {detected_count} available outfits.", "success")

    def _detected_outfit_count(self, buy_list):
        return sum(int(item[1]) for item in buy_list)

    async def debug_fake_outfit_detection(self):
        await self.process_detected_outfits(DEBUG_OUTFIT_LISTING, allow_purchase=False)

    async def debug_simulate_purchase_success(self):
        detected_count = self._detected_outfit_count(DEBUG_OUTFIT_LISTING)
        self.session_detected_outfits += detected_count
        self.add_event(f"Outfit detected: {detected_count} available outfits. Simulating purchase.", "success")

        adjusted_buy_list = await self.adjust_prices(DEBUG_OUTFIT_LISTING)
        purchase_records = [
            {
                "item_id": item_id,
                "price": int(price),
                "count": int(stock),
                "result_code": 0,
            }
            for item_id, stock, price in adjusted_buy_list
        ]
        self.record_purchase_summary(
            {
                "purchase_records": purchase_records,
                "events": [
                    {
                        "level": "success",
                        "message": f"Simulated purchase succeeded for {detected_count} outfit.",
                    }
                ],
            }
        )

    async def buy_item(self, buy_list):
        updated_buy_list = await self.adjust_prices(buy_list)
        capped_buy_list = self._apply_spend_cap(updated_buy_list)

        if not capped_buy_list:
            self.add_event("Purchase skipped: spend cap would be exceeded.", "warning")
            return

        try:
            summary = await self.api_handler.buy_item(capped_buy_list)
        except MarketplaceAPIError as exc:
            self.add_event(f"Purchase request failed: {exc}", "error")
            return

        self.record_purchase_summary(summary)

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
        remaining = self.max_spend

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
            self.add_event("Existing marketplace session is valid.", "success")
            self.start_login_status_checker()
            return

        if not self.api_handler.email or not self.api_handler.password:
            if session_check_error:
                self.add_event(
                    f"Session check failed: {session_check_error}. Configure credentials before logging in.",
                    "warning",
                )
            else:
                self.add_event("Please configure credentials before logging in.", "warning")
            return

        try:
            status = await self.api_handler.login()
        except MarketplaceAPIError as exc:
            self.api_handler.login_status = False
            if session_check_error:
                self.add_event(f"Session check failed: {session_check_error}. Login failed: {exc}", "error")
            else:
                self.add_event(f"Login failed: {exc}", "error")
            return

        if status == 1:
            self.api_handler.login_status = True
            self.api_handler.save_session()
            if session_check_error:
                self.add_event(
                    f"Session check failed: {session_check_error}. Fresh login successful; session saved.",
                    "success",
                )
            else:
                self.add_event("Login successful; session saved.", "success")
            self.start_login_status_checker()
        else:
            if session_check_error:
                self.add_event(f"Session check failed: {session_check_error}. Login failed.", "error")
            else:
                self.add_event("Login failed.", "error")

    async def initial_login_check(self):
        try:
            status = await self.api_handler.is_session_expired()
        except MarketplaceAPIError as exc:
            self.api_handler.login_status = False
            self.add_event(f"Saved marketplace session check failed: {exc}", "warning")
            return

        if status == 0:
            self.api_handler.login_status = True
            self.start_login_status_checker()
            self.add_event("Saved marketplace session is valid.", "success")
        else:
            self.api_handler.login_status = False
            self.add_event("Saved marketplace session is invalid or expired.", "warning")

    async def login_status_checker(self):
        try:
            while True:
                await asyncio.sleep(random.uniform(1800, 2400))
                try:
                    status = await self.api_handler.is_session_expired()
                except MarketplaceAPIError as exc:
                    self.add_event(f"Session check failed: {exc}", "error")
                    continue

                if status == -1:
                    self.api_handler.login_status = False
                    try:
                        login_status = await self.api_handler.login()
                    except MarketplaceAPIError as exc:
                        self.add_event(f"Session expired. Re-authentication failed: {exc}", "error")
                        break

                    if login_status == 1:
                        self.api_handler.login_status = True
                        self.api_handler.save_session()
                        self.add_event("Session expired. Re-authentication successful.", "success")
                    else:
                        self.add_event("Session expired. Re-authentication failed.", "error")
                        break
                else:
                    self.api_handler.login_status = True
                    self.add_event("Session still valid.")
        except asyncio.CancelledError:
            raise
