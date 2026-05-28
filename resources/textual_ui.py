import asyncio
import random
from typing import Optional

from rich import box
from rich.align import Align
from rich.console import Group
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Header, Input, Label, ListItem, ListView, RichLog, Select, Static, Switch

from resources.credentials import CredentialStoreError, clear_credentials, load_credentials, save_credentials
from resources.display import (
    APP_TITLE,
    APP_VERSION,
    COLOR_BRAND,
    COLOR_CAUTION,
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_SUCCESS,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
    format_compact_silver,
    format_percent,
    mask_email,
)
from resources.task_manager import LOCAL_DATA_PATH

DEFAULT_THEME = "ansi-dark"
STATUS_STYLES = {
    "success": f"bold {COLOR_SUCCESS}",
    "warning": f"bold {COLOR_WARNING}",
    "orange": f"bold {COLOR_CAUTION}",
    "error": f"bold {COLOR_ERROR}",
    "info": f"bold {COLOR_INFO}",
}

TILE_TITLE_STYLE = f"bold {COLOR_TEXT_MUTED}"

BANNER_ART = r"""
██████╗ ██████╗  ██████╗                                             ███████████
██╔══██╗██╔══██╗██╔═══██╗                                        █████████████████
██████╔╝██║  ██║██║   ██║                                      ███████     ███████
██╔══██╗██║  ██║██║   ██║                                     ██████   █   ███████
██████╔╝██████╔╝╚██████╔╝                                    █████████   █████████
╚═════╝ ╚═════╝  ╚═════╝                                     █████████████████████
███╗   ███╗ █████╗ ██████╗ ██╗  ██╗███████╗████████╗        ████  █████████  ████
████╗ ████║██╔══██╗██╔══██╗██║ ██╔╝██╔════╝╚══██╔══╝        █████████████████████
██╔████╔██║███████║██████╔╝█████╔╝ █████╗     ██║            ███████   █████████
██║╚██╔╝██║██╔══██║██╔══██╗██╔═██╗ ██╔══╝     ██║            ███████████████████
██║ ╚═╝ ██║██║  ██║██║  ██║██║  ██╗███████╗   ██║             ████████████████
╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝   ╚═╝                ███████████
""".strip("\n")

TEST_LOG_MESSAGES = [
    ("Synthetic scan completed: no outfits detected.", "info"),
    ("Synthetic outfit detected in premium category.", "success"),
    ("Synthetic purchase skipped: test spend cap reached.", "warning"),
    ("Synthetic session refresh warning for layout testing.", "warning"),
    ("Synthetic marketplace response error for log sizing.", "error"),
    ("Synthetic purchase request succeeded for one outfit.", "success"),
]


class ConfirmBuyModeScreen(Screen[bool]):
    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]
    CSS = """
    ConfirmBuyModeScreen {
        align: center middle;
    }

    #confirm-dialog {
        width: 64;
        height: auto;
        border: round $warning;
        background: $surface;
        padding: 1 2;
    }

    #confirm-actions {
        height: auto;
        margin-top: 1;
    }
    """

    def __init__(self, account: str, polling: str, spend_cap: str) -> None:
        super().__init__()
        self.account = account
        self.polling = polling
        self.spend_cap = spend_cap

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static("Confirm Buy Mode", classes="screen-heading")
            yield Static(f"Account: {self.account}")
            yield Static("Mode: Buy mode")
            yield Static(f"Polling interval: {self.polling}")
            yield Static(f"Spend cap: {self.spend_cap}")
            with Horizontal(id="confirm-actions"):
                yield Button("Start Buy Mode", id="confirm-start", variant="warning")
                yield Button("Cancel", id="confirm-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-start")

    def action_cancel(self) -> None:
        self.dismiss(False)


class MarketplaceToolsApp(App[None]):
    TITLE = f"{APP_TITLE} {APP_VERSION}"
    CSS = """
    Screen {
        background: #101010;
    }

    #shell {
        height: 1fr;
    }

    #sidebar {
        width: 23;
        min-width: 20;
        background: #171717;
        border-right: solid __COLOR_BRAND__;
        padding: 1;
    }

    #brand {
        color: __COLOR_BRAND__;
        text-style: bold;
        margin-bottom: 1;
    }

    #banner {
        height: 12;
        color: __COLOR_BRAND__;
        text-style: bold;
        overflow: hidden;
    }

    #nav {
        height: 1fr;
    }

    #add-test-log {
        width: 100%;
        margin-top: 1;
    }

    #main {
        width: 1fr;
        padding: 1 2;
    }

    .screen-heading {
        text-style: bold;
        color: __COLOR_BRAND__;
    }

    .status-message {
        color: $accent;
        margin-bottom: 1;
    }

    .panel {
        border: round #3a3a3a;
        padding: 1;
        margin-bottom: 1;
    }

    .row {
        height: auto;
        margin-bottom: 1;
    }

    .row > Label {
        width: 18;
        text-style: bold;
    }

    #dashboard-status {
        height: auto;
        padding: 0 1;
        margin-bottom: 0;
        border-title-color: __COLOR_BRAND__;
        border-title-style: bold;
    }

    #event-log {
        height: 1fr;
        min-height: 6;
        border: round #3a3a3a;
        border-title-color: __COLOR_BRAND__;
        border-title-style: bold;
    }

    #content {
        height: 1fr;
        overflow-y: auto;
    }

    Input, Select {
        width: 60;
    }

    Button {
        margin-right: 1;
    }
    """.replace("__COLOR_BRAND__", COLOR_BRAND)

    BINDINGS = [
        Binding("escape", "show_dashboard", "Dashboard"),
        Binding("q", "quit_app", "Quit"),
        Binding("ctrl+c", "quit_app", "Quit", show=False),
    ]

    NAV_ITEMS = [
        ("dashboard", "Dashboard"),
        ("credentials", "Credentials"),
        ("login", "Login / Refresh"),
        ("start", "Start Monitor"),
        ("stop", "Stop Monitor"),
        ("settings", "Settings"),
        ("wallet", "Marketplace Wallet"),
        ("stats", "Stats"),
        ("exit", "Exit"),
    ]

    NUMBER_NAV = {
        "1": "credentials",
        "2": "login",
        "3": "start",
        "4": "stop",
        "5": "settings",
        "6": "wallet",
        "7": "stats",
        "8": "exit",
    }

    def __init__(self, task_manager, api_handler, launch_mode: str = "live") -> None:
        super().__init__()
        self.theme = DEFAULT_THEME
        self.task_manager = task_manager
        self.api_handler = api_handler
        self.launch_mode = launch_mode
        self.current_view = "dashboard"
        self.status_message = "Test mode: startup session check skipped." if launch_mode == "test" else ""
        self._rendered_events: tuple[str, ...] = ()
        self._dashboard_snapshot: tuple[str, ...] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="shell"):
            with Vertical(id="sidebar"):
                yield Static(f"{APP_TITLE}\n{APP_VERSION}", id="brand")
                yield ListView(
                    *[
                        ListItem(Label(label), id=f"nav-{key}")
                        for key, label in self.NAV_ITEMS
                    ],
                    id="nav",
                )
                yield Button("Add Test Log", id="add-test-log")
            with Vertical(id="main"):
                yield Static(BANNER_ART, id="banner")
                yield Static("", id="screen-title", classes="screen-heading")
                yield Static("", id="status-message", classes="status-message")
                yield Container(id="content")

    async def on_mount(self) -> None:
        self.query_one("#nav", ListView).index = 0
        await self.show_view("dashboard")
        self.set_interval(1, self.refresh_live_widgets)

    def on_resize(self, event) -> None:
        self.refresh_layout_density()

    async def on_unmount(self) -> None:
        await self.task_manager.stop_checker()
        await self.task_manager.stop_login_status_checker()
        self.api_handler.save_session()

    async def on_key(self, event) -> None:
        if isinstance(self.focused, Input):
            return
        target = self.NUMBER_NAV.get(event.key)
        if target:
            event.stop()
            await self.handle_nav(target)

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        if item_id.startswith("nav-"):
            await self.handle_nav(item_id.removeprefix("nav-"))

    async def handle_nav(self, target: str) -> None:
        if target == "login":
            self.run_worker(self.login_refresh(), name="login-refresh", group="actions", exclusive=True)
            return
        if target == "start":
            await self.start_monitor()
            return
        if target == "stop":
            await self.task_manager.stop_checker()
            self.set_status("Monitor stopped.")
            self.refresh_live_widgets()
            return
        if target == "exit":
            await self.action_quit_app()
            return
        await self.show_view(target)

    async def show_view(self, view_name: str) -> None:
        self.current_view = view_name
        content = self.query_one("#content", Container)
        await content.remove_children()

        title = dict(self.NAV_ITEMS).get(view_name, "Dashboard")
        self.query_one("#screen-title", Static).update(title)
        self.update_chrome_visibility()

        if view_name == "dashboard":
            dashboard_status = Static(id="dashboard-status", classes="panel")
            dashboard_status.border_title = "Dashboard"
            event_log = RichLog(id="event-log", markup=True, highlight=False, wrap=True)
            event_log.border_title = "Event Log"
            await content.mount(dashboard_status)
            await content.mount(event_log)
        elif view_name == "credentials":
            await self.mount_credentials(content)
        elif view_name == "settings":
            await self.mount_settings(content)
        elif view_name == "wallet":
            await self.mount_wallet(content)
        elif view_name == "stats":
            await self.mount_stats(content)

        self.refresh_live_widgets()
        self.refresh_layout_density()

    def set_status(self, message: str) -> None:
        self.status_message = message
        status = self.query_one("#status-message", Static)
        status.update(message)
        self.update_chrome_visibility()

    def credential_state(self) -> tuple[str, str, str, Optional[str], Optional[str]]:
        try:
            email, password = load_credentials()
        except CredentialStoreError as exc:
            self.api_handler.email = None
            self.api_handler.password = None
            return "Credential Store Error", str(exc), "error", None, None

        self.api_handler.email = email
        self.api_handler.password = password
        if email and password:
            return "Ready", mask_email(email), "success", email, password
        if email:
            return "Password Needed", mask_email(email), "warning", email, password
        return "Not Set", "No account configured", "error", email, password

    def dashboard_snapshot(self) -> tuple[str, ...]:
        credential_status, credential_detail, credential_level, _, _ = self.credential_state()
        login_status = "ONLINE" if self.api_handler.login_status else "OFFLINE"
        monitor_status = "Running" if self.task_manager.checker_enabled else "Stopped"
        mode = "Buy mode" if self.task_manager.purchase_submission_enabled else "Watch only"
        purchase_rate = format_percent(
            self.task_manager.session_successful_purchases,
            self.task_manager.session_detected_outfits,
        )
        purchase_detail = (
            f"{self.task_manager.session_successful_purchases}/"
            f"{self.task_manager.session_detected_outfits} bought this session"
        )
        spend_detail = f"Cap: {format_compact_silver(self.task_manager.max_spend)} per cycle"

        return (
            credential_status,
            credential_detail,
            credential_level,
            login_status,
            monitor_status,
            mode,
            self.task_manager.current_delay_label(),
            self.task_manager.current_delay_range(),
            purchase_rate,
            purchase_detail,
            format_compact_silver(self.task_manager.session_silver_spent),
            spend_detail,
            self.task_manager.runtime_label(),
        )

    def status_table(self, snapshot: tuple[str, ...] | None = None) -> Group:
        snapshot = snapshot or self.dashboard_snapshot()
        (
            credential_status,
            credential_detail,
            credential_level,
            login_status,
            monitor_status,
            mode,
            delay_label,
            delay_range,
            purchase_rate,
            purchase_detail,
            silver_spent,
            spend_detail,
            runtime,
        ) = snapshot

        def metric_tile(label: str, value: str, detail: str, level: str = "info") -> Panel:
            body = Text()
            body.append(f"{value}\n", style=STATUS_STYLES[level])
            body.append(detail, style="dim")
            return Panel(
                Align.center(body, vertical="middle"),
                title=Text(label, style=TILE_TITLE_STYLE),
                border_style="#3a3a3a",
                box=box.ROUNDED,
                padding=(0, 1),
            )

        purchase_tile_detail = purchase_detail.replace(" this session", "")
        spend_tile_detail = spend_detail.replace(" per cycle", "")

        metrics = Table.grid(expand=True)
        metrics.add_column(ratio=1)
        metrics.add_column(ratio=1)
        metrics.add_column(ratio=1)
        metrics.add_column(ratio=1)
        metrics.add_row(
            metric_tile("Monitor", monitor_status, mode, "success" if self.task_manager.checker_enabled else "error"),
            metric_tile("Success", purchase_rate, purchase_tile_detail, self.purchase_rate_level()),
            metric_tile("Spent", silver_spent, spend_tile_detail),
            metric_tile("Runtime", runtime, "Active session"),
        )

        details = Table.grid(expand=True)
        details.add_column("Label", style="bold", no_wrap=True, width=13)
        details.add_column("Value", no_wrap=True, width=20)
        details.add_column("Detail", style="dim", no_wrap=True, overflow="ellipsis")
        details.add_row("Credentials", Text(credential_status, style=STATUS_STYLES[credential_level]), credential_detail)
        details.add_row(
            "Session",
            Text(login_status, style=STATUS_STYLES["success" if self.api_handler.login_status else "error"]),
            "Marketplace authentication",
        )
        details.add_row("Polling", Text(delay_label, style=STATUS_STYLES["info"]), delay_range)

        return Group(metrics, details)

    def purchase_rate_level(self) -> str:
        detected = self.task_manager.session_detected_outfits
        if detected <= 0:
            return "error"

        percentage = (self.task_manager.session_successful_purchases / detected) * 100
        if percentage >= 80:
            return "success"
        if percentage >= 50:
            return "warning"
        if percentage >= 25:
            return "orange"
        return "error"

    def refresh_live_widgets(self) -> None:
        if self.current_view == "dashboard":
            try:
                snapshot = self.dashboard_snapshot()
                if snapshot != self._dashboard_snapshot:
                    self.query_one("#dashboard-status", Static).update(self.status_table(snapshot))
                    self._dashboard_snapshot = snapshot
                self.sync_event_log()
            except Exception:
                pass
        elif self.current_view == "credentials":
            self.refresh_credentials_summary()
        elif self.current_view == "stats":
            self.refresh_stats()

    def should_show_banner(self) -> bool:
        size = self.size
        return self.current_view == "dashboard" and size.width >= 96 and size.height >= 34

    def refresh_layout_density(self) -> None:
        try:
            self.query_one("#banner", Static).display = self.should_show_banner()
            self.update_chrome_visibility()
        except Exception:
            pass

    def update_chrome_visibility(self) -> None:
        title = self.query_one("#screen-title", Static)
        status = self.query_one("#status-message", Static)
        title.display = self.current_view != "dashboard"
        status.display = bool(self.status_message)
        status.update(self.status_message)

    def sync_event_log(self) -> None:
        events = tuple(self.task_manager.events)
        if events == self._rendered_events:
            return

        log = self.query_one("#event-log", RichLog)
        log.clear()
        if events:
            for event in events:
                log.write(event)
        else:
            log.write("No events yet.")
        self._rendered_events = events

    async def mount_credentials(self, content: Container) -> None:
        _, _, _, email, _ = self.credential_state()
        await content.mount(Static(id="credentials-summary", classes="panel"))
        await content.mount(Label("Email"))
        await content.mount(Input(value=email or "", placeholder="account@example.com", id="email-input"))
        await content.mount(Label("Password"))
        await content.mount(Input(password=True, placeholder="Stored in OS keyring", id="password-input"))
        await content.mount(
            Horizontal(
                Button("Save Credentials", id="save-credentials", variant="primary"),
                Button("Clear Saved Credentials", id="clear-credentials", variant="error"),
                classes="row",
            )
        )
        self.refresh_credentials_summary()

    def refresh_credentials_summary(self) -> None:
        try:
            summary = self.query_one("#credentials-summary", Static)
        except Exception:
            return
        state, detail, _, _, password = self.credential_state()
        password_detail = "Stored in OS keyring" if password else "Not set"
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold")
        table.add_column()
        table.add_row("Email", detail)
        table.add_row("Password", password_detail)
        table.add_row("Status", state)
        summary.update(table)

    async def mount_settings(self, content: Container) -> None:
        delay_options = [
            (f"{label} ({low}-{high}s)", key)
            for key, (label, (low, high)) in self.task_manager.delay_choices.items()
        ]
        await content.mount(Static(id="settings-summary", classes="panel"))
        await content.mount(Label("Polling interval"))
        await content.mount(Select(delay_options, value=self.task_manager.delay, id="delay-select"))
        await content.mount(Label("Buy mode"))
        await content.mount(Switch(value=self.task_manager.purchase_submission_enabled, id="buy-mode-switch"))
        await content.mount(Label("Spend cap in silver"))
        await content.mount(
            Input(
                value=str(self.task_manager.max_spend or 0),
                type="integer",
                placeholder="0 for no cap",
                id="spend-cap-input",
            )
        )
        await content.mount(Button("Save Settings", id="save-settings", variant="primary"))
        self.refresh_settings_summary()

    def refresh_settings_summary(self) -> None:
        try:
            summary = self.query_one("#settings-summary", Static)
        except Exception:
            return
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold")
        table.add_column()
        mode = "Buy mode" if self.task_manager.purchase_submission_enabled else "Watch only"
        table.add_row("Mode", mode)
        table.add_row("Polling interval", f"{self.task_manager.current_delay_label()} ({self.task_manager.current_delay_range()})")
        table.add_row("Spend cap", format_compact_silver(self.task_manager.max_spend))
        table.add_row("Tracked categories", "Outfits: male and female marketplace categories")
        summary.update(table)

    async def mount_wallet(self, content: Container) -> None:
        await content.mount(Button("Refresh Wallet", id="refresh-wallet", variant="primary"))
        await content.mount(Static("Wallet data has not been loaded yet.", id="wallet-output", classes="panel"))

    async def mount_stats(self, content: Container) -> None:
        await content.mount(Button("Refresh Stats", id="refresh-stats", variant="primary"))
        await content.mount(Static(id="stats-output", classes="panel"))
        self.refresh_stats()

    def refresh_stats(self) -> None:
        try:
            output = self.query_one("#stats-output", Static)
        except Exception:
            return
        self.task_manager.reload_lifetime_stats()
        table = Table(expand=True)
        table.add_column("Metric", style="bold")
        table.add_column("Value")
        table.add_row("Lifetime Purchases", str(self.task_manager.lifetime_successful_purchases))
        table.add_row("Lifetime Silver Spent", format_compact_silver(self.task_manager.lifetime_silver_spent))
        table.add_row("Local Data File", str(LOCAL_DATA_PATH))
        output.update(table)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "save-credentials":
            await self.save_credential_inputs()
        elif button_id == "clear-credentials":
            await self.clear_saved_credentials()
        elif button_id == "save-settings":
            self.save_settings()
        elif button_id == "refresh-wallet":
            self.run_worker(self.refresh_wallet(), name="wallet-refresh", group="actions", exclusive=True)
        elif button_id == "refresh-stats":
            self.refresh_stats()
            self.set_status("Stats refreshed.")
        elif button_id == "add-test-log":
            await self.add_test_log()

    async def add_test_log(self) -> None:
        message, level = random.choice(TEST_LOG_MESSAGES)
        self.task_manager.add_event(message, level)
        if self.current_view != "dashboard":
            await self.show_view("dashboard")
            return
        self.refresh_live_widgets()

    async def save_credential_inputs(self) -> None:
        email = self.query_one("#email-input", Input).value.strip()
        password = self.query_one("#password-input", Input).value
        if not email:
            self.set_status("Email field cannot be empty.")
            return
        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            self.set_status("Enter a valid email address.")
            return
        if not password:
            self.set_status("Password field cannot be empty.")
            return

        self.api_handler.email = email
        self.api_handler.password = password
        try:
            save_credentials(email, password)
        except CredentialStoreError as exc:
            self.task_manager.add_event(f"Unable to save credentials: {exc}", "error")
            self.set_status("Unable to save credentials.")
            return

        self.query_one("#password-input", Input).value = ""
        self.set_status("Credentials saved.")
        self.refresh_credentials_summary()

    async def clear_saved_credentials(self) -> None:
        try:
            clear_credentials()
        except CredentialStoreError as exc:
            self.task_manager.add_event(f"Unable to clear credentials: {exc}", "error")
            self.set_status("Unable to clear saved credentials.")
            return

        self.api_handler.email = None
        self.api_handler.password = None
        self.query_one("#email-input", Input).value = ""
        self.query_one("#password-input", Input).value = ""
        self.set_status("Saved credentials cleared.")
        self.refresh_credentials_summary()

    def save_settings(self) -> None:
        delay = self.query_one("#delay-select", Select).value
        spend_value = self.query_one("#spend-cap-input", Input).value.strip() or "0"
        buy_mode = self.query_one("#buy-mode-switch", Switch).value

        try:
            spend_cap = int(spend_value)
            if spend_cap < 0:
                raise ValueError
        except ValueError:
            self.set_status("Spend cap must be 0 or a positive integer.")
            return

        if delay in self.task_manager.delay_choices:
            self.task_manager.delay = str(delay)
        self.task_manager.purchase_submission_enabled = bool(buy_mode)
        self.task_manager.max_spend = spend_cap or None
        self.set_status("Settings saved.")
        self.refresh_settings_summary()
        self.refresh_live_widgets()

    async def login_refresh(self) -> None:
        self.set_status("Checking marketplace session...")
        await self.task_manager.login()
        self.set_status("Login check complete.")
        self.refresh_live_widgets()

    async def start_monitor(self) -> None:
        if self.task_manager.purchase_submission_enabled and not self.api_handler.login_status:
            self.task_manager.add_event("Login required before starting the monitor.", "warning")
            self.set_status("Login or refresh the marketplace session before starting buy mode.")
            self.refresh_live_widgets()
            return

        if self.task_manager.purchase_submission_enabled:
            self.push_screen(
                ConfirmBuyModeScreen(
                    account=mask_email(self.api_handler.email),
                    polling=f"{self.task_manager.current_delay_label()} ({self.task_manager.current_delay_range()})",
                    spend_cap=format_compact_silver(self.task_manager.max_spend),
                ),
                callback=self._handle_buy_mode_confirmation,
            )
            return

        await self._start_monitor_now()

    def _handle_buy_mode_confirmation(self, confirmed: bool) -> None:
        if not confirmed:
            self.set_status("Buy mode start canceled.")
            return
        self.run_worker(self._start_monitor_now(), name="start-buy-mode", group="actions", exclusive=True)

    async def _start_monitor_now(self) -> None:
        await self.task_manager.start_checker()
        mode = "buy mode" if self.task_manager.purchase_submission_enabled else "watch-only mode"
        self.set_status(f"Monitor started in {mode}.")
        await self.show_view("dashboard")

    async def refresh_wallet(self) -> None:
        self.set_status("Loading marketplace wallet...")
        try:
            response = await self.api_handler.get_mp_inventory()
        except Exception as exc:
            self.task_manager.add_event(f"Wallet lookup failed: {exc}", "error")
            self.set_status("Wallet lookup failed.")
            try:
                self.query_one("#wallet-output", Static).update(str(exc))
            except Exception:
                pass
            return

        self.query_one("#wallet-output", Static).update(JSON.from_data(response))
        self.set_status("Wallet loaded.")

    def action_show_dashboard(self) -> None:
        self.run_worker(self.show_view("dashboard"), name="show-dashboard", group="navigation", exclusive=True)

    async def action_quit_app(self) -> None:
        await self.task_manager.stop_checker()
        await self.task_manager.stop_login_status_checker()
        self.api_handler.save_session()
        self.exit()
