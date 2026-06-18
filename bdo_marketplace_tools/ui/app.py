import asyncio
import random
from typing import Optional

from rich.align import Align
from rich.console import Group, RenderableType
from rich.json import JSON
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label, ListItem, ListView, RichLog, Select, Static, Switch

from bdo_marketplace_tools.market.api_handler import marketplace_silver_balance
from bdo_marketplace_tools.market.test_mode import SINGLE_ITEM_TEST_TARGET
from bdo_marketplace_tools.storage.app_settings import ACCOUNT_MODE_LABELS, PA_CREDENTIALS_MODE, STEAM_BROWSER_MODE
from bdo_marketplace_tools.storage.credentials import CredentialStoreError, clear_credentials, load_credentials, save_credentials
from bdo_marketplace_tools.version import SETTINGS_SCHEMA_VERSION
from bdo_marketplace_tools.ui.display import (
    APP_CHANNEL,
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
from bdo_marketplace_tools.ui.modals import (
    BuyDelayModal,
    ConfirmBuyModeScreen,
    CredentialsModal,
    DashboardModalScreen,
    MonitorModal,
    PACredentialsModal,
    PollingModal,
    SessionModal,
    SessionRefreshConfirmScreen,
    SpendCapModal,
)
from bdo_marketplace_tools.ui.theme import BANNER_ART, DEFAULT_THEME, STATUS_DOT, STATUS_STYLES, TEST_LOG_MESSAGES
from bdo_marketplace_tools.ui.widgets import (
    AppHeader,
    CredentialActionTile,
    DashboardTile,
    LogFilterOption,
    ModalAction,
    PollingPresetTile,
    SteamSetupTile,
)


class MarketplaceToolsApp(App[None]):
    TITLE = APP_TITLE
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
        padding: 1 1 0 1;
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
        margin-bottom: 1;
    }

    #nav {
        height: auto;
        margin-bottom: 1;
    }

    #sidebar-spacer {
        height: 1fr;
    }

    #build-info {
        height: 1;
        color: __COLOR_TEXT_MUTED__;
        text-style: dim;
    }

    #test-controls {
        height: 1fr;
        min-height: 6;
        margin-top: 1;
        overflow-y: auto;
    }

    #test-controls Button {
        width: 100%;
        min-width: 0;
        margin: 0;
        text-align: left;
        content-align: left middle;
    }

    #main {
        width: 1fr;
        padding: 0 2;
    }

    .screen-heading {
        text-style: bold;
        color: __COLOR_BRAND__;
    }

    .panel {
        border: round #3a3a3a;
        padding: 1;
        margin-bottom: 1;
    }

    .settings-panel {
        border: round #3a3a3a;
        border-title-color: #d8d3c8;
        border-title-style: bold;
        padding: 1;
        margin-bottom: 1;
    }

    .settings-note {
        color: __COLOR_TEXT_MUTED__;
        margin-bottom: 1;
    }

    #settings-actions {
        height: auto;
    }

    .row {
        height: auto;
        margin-bottom: 1;
    }

    .row > Label {
        width: 18;
        text-style: bold;
    }

    #dashboard-panel {
        height: auto;
        margin-bottom: 1;
    }

    #dashboard-tiles {
        height: 8;
    }

    #dashboard-action-tiles {
        width: 1fr;
        height: 8;
        margin-right: 1;
    }

    #dashboard-info-tiles {
        width: 21;
        height: 8;
    }

    .dashboard-tile-row {
        height: 4;
    }

    .dashboard-tile-column {
        width: 1fr;
        height: 8;
    }

    .dashboard-tile {
        width: 1fr;
        height: 4;
        min-width: 10;
        margin-right: 1;
        padding: 0 1;
        content-align: center middle;
        border-title-align: center;
    }

    .tile-clickable {
        border: round #d8d3c8;
        border-title-color: #d8d3c8;
        border-title-style: bold;
        color: #d8d3c8;
    }

    .tile-clickable:hover {
        border: round __COLOR_BRAND__;
        border-title-color: __COLOR_BRAND__;
    }

    .tile-clickable:focus {
        border: round __COLOR_BRAND__;
        border-title-color: __COLOR_BRAND__;
    }

    .tile-muted {
        border: round #2b2b2b;
        border-title-color: #777777;
        border-title-style: bold;
        color: #777777;
    }

    #event-log {
        height: 1fr;
        min-height: 6;
        border: round #3a3a3a;
        border-title-color: #d8d3c8;
        border-title-style: bold;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
        scrollbar-color: #343434;
        scrollbar-color-hover: #4a4a4a;
        scrollbar-color-active: #5f5f5f;
        scrollbar-background: #111111;
        scrollbar-background-hover: #111111;
        scrollbar-background-active: #111111;
        scrollbar-corner-color: #111111;
    }

    #event-log-toolbar {
        height: 1;
        margin-bottom: 0;
    }

    #event-log-toolbar-title {
        width: 16;
        color: __COLOR_TEXT_MUTED__;
        text-style: bold;
    }

    #log-filter-separator {
        width: 3;
        content-align: center middle;
        color: #777777;
    }

    .log-filter-option {
        width: 10;
        height: 1;
        margin-right: 1;
        content-align: center middle;
        color: __COLOR_TEXT_MUTED__;
        background: transparent;
    }

    .log-filter-option:hover {
        color: __COLOR_BRAND__;
    }

    .log-filter-selected {
        color: __COLOR_BRAND__;
        text-style: bold;
    }

    #stats-actions,
    #wallet-actions {
        height: auto;
        margin-bottom: 1;
    }

    .wip-note {
        border: round #3a3a3a;
        border-title-color: __COLOR_BRAND__;
        color: __COLOR_TEXT_MUTED__;
        padding: 0 1;
        margin: 1 0 1 0;
    }

    .modal-action-tile {
        width: 18;
        height: 3;
        margin-right: 1;
        content-align: center middle;
        border: round #d8d3c8;
        color: #d8d3c8;
        background: transparent;
    }

    .modal-action-tile:hover {
        border: round __COLOR_BRAND__;
        color: __COLOR_BRAND__;
        background: transparent;
    }

    .stats-section-title {
        color: __COLOR_BRAND__;
        text-style: bold;
        margin-bottom: 1;
    }

    .stats-row {
        height: 4;
        margin-bottom: 1;
    }

    .stats-tile {
        width: 1fr;
        height: 4;
        min-width: 12;
        margin-right: 1;
        padding: 0 1;
        content-align: center middle;
        border: round #3a3a3a;
        border-title-color: #d8d3c8;
        border-title-style: bold;
        border-title-align: center;
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
    """.replace("__COLOR_BRAND__", COLOR_BRAND).replace("__COLOR_TEXT_MUTED__", COLOR_TEXT_MUTED)

    BINDINGS = [
        Binding("escape", "show_dashboard", "Dashboard"),
        Binding("q", "quit_app", "Quit"),
        Binding("ctrl+c", "quit_app", "Quit", show=False),
    ]

    NAV_ITEMS = [
        ("dashboard", "Dashboard"),
        ("settings", "App Settings"),
        ("wallet", "Inventory"),
        ("stats", "Stats"),
        ("exit", "Exit"),
    ]

    VIEW_TITLES = {
        "wallet": "Marketplace Inventory",
    }

    NUMBER_NAV = {
        "1": "settings",
        "2": "wallet",
        "3": "stats",
        "4": "exit",
    }

    def __init__(self, task_manager, api_handler, launch_mode: str = "live") -> None:
        super().__init__()
        self.theme = DEFAULT_THEME
        self.task_manager = task_manager
        self.api_handler = api_handler
        self.launch_mode = launch_mode
        self.task_manager.test_mode_enabled = self.is_test_mode
        self.current_view = "dashboard"
        self.status_message = ""
        self.event_log_mode = self.task_manager.event_log_view
        self._rendered_events: tuple[str, ...] | None = None
        self._dashboard_snapshot: tuple[str, ...] | None = None
        self._syncing_controls = False

    def compose(self) -> ComposeResult:
        yield AppHeader(id="app-header")
        with Horizontal(id="shell"):
            with Vertical(id="sidebar"):
                yield Static(APP_TITLE, id="brand")
                yield ListView(
                    *[
                        ListItem(Label(label), id=f"nav-{key}")
                        for key, label in self.NAV_ITEMS
                    ],
                    id="nav",
                )
                if self.is_test_mode:
                    with VerticalScroll(id="test-controls"):
                        yield Button("Add Test Log", id="add-test-log", compact=True)
                        yield Button("Toggle Test Session", id="toggle-test-session", compact=True)
                        yield Button("Auto Reauth", id="toggle-auto-reauth", compact=True)
                        yield Button("Expire Session", id="expire-test-session", compact=True)
                        yield Button("Reauth Check", id="run-reauth-check", compact=True)
                        yield Button("Blank Browser", id="open-blank-browser", compact=True)
                        yield Button("Reset Steam Setup", id="reset-steam-setup", compact=True)
                        yield Button("Clear Browser Cookies", id="clear-browser-cookies", compact=True)
                        yield Button("Start Test Scan", id="start-test-monitor", compact=True)
                        yield Button("Start Test Buy", id="start-test-buy", compact=True)
                        yield Button("Stop Test Scan", id="stop-test-monitor", compact=True)
                        yield Button("Fake Detection", id="fake-detection", compact=True)
                        yield Button("Fake Buy Success", id="fake-buy-success", compact=True)
                else:
                    yield Static("", id="sidebar-spacer")
                yield Static(f"v{APP_VERSION}", id="build-info")
            with Vertical(id="main"):
                yield Static(BANNER_ART, id="banner")
                yield Static("", id="screen-title", classes="screen-heading")
                yield Container(id="content")

    @property
    def is_test_mode(self) -> bool:
        return self.launch_mode == "test"

    @property
    def is_simulated_session(self) -> bool:
        return bool(getattr(self.task_manager, "simulated_session_enabled", False))

    async def on_mount(self) -> None:
        self.query_one("#nav", ListView).index = 0
        await self.show_view("dashboard")
        self.set_interval(1, self.refresh_live_widgets)

    def on_resize(self, event) -> None:
        self.refresh_layout_density()

    async def on_unmount(self) -> None:
        await self.task_manager.stop_checker()
        await self.task_manager.stop_single_item_test_checker()
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
            await self.stop_monitor()
            return
        if target == "exit":
            await self.action_quit_app()
            return
        await self.show_view(target)

    async def toggle_monitor_from_dashboard(self) -> None:
        if self.task_manager.checker_enabled:
            await self.stop_monitor()
            return

        await self.start_monitor()

    async def stop_monitor(self, close_modal: bool = False) -> None:
        if self.task_manager.single_item_test_checker_enabled and not self.task_manager.checker_enabled:
            was_running = await self.task_manager.stop_single_item_test_checker()
            if was_running:
                self.set_status("Single-item test monitor stopped.", "info")
            else:
                self.set_status("Monitor already stopped.", "info")
            self.refresh_live_widgets()
            if close_modal:
                self.close_active_dashboard_modal()
            return

        was_running = await self.task_manager.stop_checker()
        if was_running:
            self.set_status("Monitor stopped.", "info")
        else:
            self.set_status("Monitor already stopped.", "info")
        self.refresh_live_widgets()
        if close_modal:
            self.close_active_dashboard_modal()

    async def show_view(self, view_name: str) -> None:
        self.current_view = view_name
        content = self.query_one("#content", Container)
        await content.remove_children()

        title = self.VIEW_TITLES.get(view_name, dict(self.NAV_ITEMS).get(view_name, "Dashboard"))
        self.query_one("#screen-title", Static).update(title)
        self.update_chrome_visibility()

        if view_name == "dashboard":
            dashboard_tiles = Horizontal(
                Horizontal(
                    Vertical(
                        DashboardTile("monitor", "Monitor"),
                        DashboardTile("session", "Session"),
                        id="dashboard-monitor-column",
                        classes="dashboard-tile-column",
                    ),
                    Vertical(
                        DashboardTile("spent", "Spent"),
                        DashboardTile("credentials", "Credentials"),
                        id="dashboard-account-column",
                        classes="dashboard-tile-column",
                    ),
                    Vertical(
                        DashboardTile("polling", "Polling"),
                        DashboardTile("buy-delay", "Buy Delay"),
                        id="dashboard-delay-column",
                        classes="dashboard-tile-column",
                    ),
                    id="dashboard-action-tiles",
                ),
                Vertical(
                    DashboardTile("success", "Success Rate", interactive=False),
                    DashboardTile("runtime", "Runtime", interactive=False),
                    id="dashboard-info-tiles",
                ),
                id="dashboard-tiles",
            )
            dashboard_panel = Vertical(id="dashboard-panel")
            event_log = RichLog(id="event-log", markup=True, highlight=False, wrap=True)
            event_log.border_title = "Event Log"
            event_toolbar = Horizontal(
                Static("Event Log View:", id="event-log-toolbar-title"),
                LogFilterOption("core", "Core logs"),
                Static("/", id="log-filter-separator"),
                LogFilterOption("ui", "UI logs"),
                id="event-log-toolbar",
            )
            await content.mount(dashboard_panel)
            await dashboard_panel.mount(dashboard_tiles)
            await content.mount(event_toolbar)
            await content.mount(event_log)
            self._dashboard_snapshot = None
            self._rendered_events = None
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

    def set_status(self, message: str, level: str | None = None) -> None:
        self.status_message = message
        if message and level:
            self.task_manager.add_event(message, level, channel="ui")
        self.refresh_live_widgets()

    def query_visible_one(self, selector: str, expect_type=None):
        screens = list(reversed(self.screen_stack))
        for screen in screens:
            try:
                if expect_type is None:
                    return screen.query_one(selector)
                return screen.query_one(selector, expect_type)
            except Exception:
                continue
        if expect_type is None:
            return self.query_one(selector)
        return self.query_one(selector, expect_type)

    def close_active_dashboard_modal(self) -> None:
        if self.screen_stack and isinstance(self.screen_stack[-1], DashboardModalScreen):
            self.screen_stack[-1].dismiss(None)

    def close_dashboard_modals(self) -> None:
        while self.screen_stack and isinstance(self.screen_stack[-1], DashboardModalScreen):
            self.screen_stack[-1].dismiss(None)

    def credential_state(self) -> tuple[str, str, str, Optional[str], Optional[str]]:
        if self.task_manager.uses_steam_browser_session():
            self.api_handler.email = None
            self.api_handler.password = None
            if self.task_manager.steam_browser_profile_needs_setup():
                return "Steam Setup", "Initial setup needed", "warning", None, None
            return "Steam Account", "Browser login", "steam", None, None

        state, detail, level, email, password = self.pa_credential_state()
        self.api_handler.email = email
        self.api_handler.password = password
        return state, detail, level, email, password

    def pa_credential_state(self) -> tuple[str, str, str, Optional[str], Optional[str]]:
        try:
            email, password = load_credentials()
        except CredentialStoreError as exc:
            return "Credential Store Error", str(exc), "error", None, None

        if email and password:
            return "PA Account", mask_email(email), "gold", email, password
        if email:
            return "Password Needed", mask_email(email), "warning", email, password
        return "Not Set", "No account configured", "error", email, password

    def delay_options(self) -> list[tuple[str, str]]:
        options = [
            (f"{label} ({low}-{high}s)", key)
            for key, (label, (low, high)) in self.task_manager.delay_choices.items()
        ]
        options.append((f"Custom ({self.task_manager.current_delay_range()})", "custom"))
        return options

    def session_status_state(self) -> tuple[str, str, str]:
        if self.is_simulated_session:
            return "TEST", "Simulated auth", "warning"
        if self.task_manager.uses_steam_browser_session():
            if self.api_handler.login_status:
                return "ONLINE", "Authenticated", "success"
            return "OFFLINE", "Refresh required", "error"
        if self.api_handler.login_status:
            return "ONLINE", "Authenticated", "success"
        return "OFFLINE", "Refresh required", "error"

    def session_account_label(self) -> str:
        if self.is_simulated_session:
            return "Test session"
        if self.task_manager.uses_steam_browser_session():
            return "Steam Account"
        if self.api_handler.email:
            return mask_email(self.api_handler.email)
        return "No account configured"

    def dashboard_snapshot(self) -> tuple[str, ...]:
        credential_status, credential_detail, credential_level, _, _ = self.credential_state()
        login_status, _, _ = self.session_status_state()
        monitor_status = self.task_manager.monitor_status_label()
        mode = self.task_manager.monitor_mode_label()
        purchase_rate = format_percent(
            self.task_manager.session_successful_purchases,
            self.task_manager.session_detected_outfits,
        )
        purchase_detail = (
            f"{self.task_manager.session_successful_purchases}/"
            f"{self.task_manager.session_detected_outfits} bought this session"
        )
        spend_detail = f"Cap: {format_compact_silver(self.task_manager.max_spend)} this session"

        return (
            credential_status,
            credential_detail,
            credential_level,
            login_status,
            monitor_status,
            mode,
            self.task_manager.current_delay_label(),
            self.task_manager.current_delay_range(),
            self.task_manager.purchase_delay_range(),
            purchase_rate,
            purchase_detail,
            format_compact_silver(self.task_manager.session_silver_spent),
            spend_detail,
            self.task_manager.runtime_label(),
        )

    def status_text(self, value: str, level: str, show_dot: bool = True) -> Text:
        text = Text()
        if show_dot:
            text.append(f"{STATUS_DOT} ", style=STATUS_STYLES[level])
        text.append(value, style=STATUS_STYLES[level])
        return text

    def dashboard_tile_data(self, snapshot: tuple[str, ...]) -> list[tuple[str, str, str, str, bool]]:
        (
            credential_status,
            credential_detail,
            credential_level,
            login_status,
            monitor_status,
            mode,
            delay_label,
            delay_range,
            purchase_delay_range,
            purchase_rate,
            purchase_detail,
            silver_spent,
            spend_detail,
            runtime,
        ) = snapshot

        purchase_tile_detail = purchase_detail.replace(" this session", "")
        spend_tile_detail = spend_detail.replace(" this session", "")
        credential_tile_detail = "No account" if credential_detail == "No account configured" else credential_detail
        monitor_level = "success" if self.task_manager.monitor_running() else "error"
        _session_label, session_detail, session_level = self.session_status_state()

        return [
            ("monitor", monitor_status, mode, monitor_level, True),
            ("spent", silver_spent, spend_tile_detail, "info", False),
            ("polling", delay_label, delay_range, "info", False),
            ("buy-delay", purchase_delay_range, "Between buys", "info", False),
            ("credentials", credential_status, credential_tile_detail, credential_level, True),
            (
                "session",
                login_status,
                session_detail,
                session_level,
                True,
            ),
            ("success", purchase_rate, purchase_tile_detail, self.purchase_rate_level(), False),
            ("runtime", runtime, "Active session", "muted", False),
        ]

    def tile_renderable(
        self,
        value: str,
        detail: str,
        level: str,
        show_dot: bool,
        muted: bool = False,
        subdued: bool = False,
    ) -> RenderableType:
        body = Table.grid(expand=True)
        body.add_column(justify="center")
        if subdued and level != "info":
            value_text = self.status_text(value, level, show_dot=show_dot)
            detail_style = "#5f5f5f"
        elif subdued:
            value_text = Text()
            if show_dot:
                value_text.append(f"{STATUS_DOT} ", style="#8f8f8f")
            value_text.append(value, style="#9a9a9a")
            detail_style = "#5f5f5f"
        elif muted and level == "muted":
            value_text = Text(value, style="dim #aaaaaa")
            detail_style = "#777777"
        else:
            value_text = self.status_text(value, level, show_dot=show_dot)
            detail_style = "dim"
        body.add_row(value_text)
        body.add_row(Text(detail, style=detail_style))
        return Align.center(body, vertical="middle")

    def refresh_dashboard_tiles(self, snapshot: tuple[str, ...]) -> None:
        for tile_key, value, detail, level, show_dot in self.dashboard_tile_data(snapshot):
            tile = self.query_one(f"#tile-{tile_key}", DashboardTile)
            tile.update(self.tile_renderable(value, detail, level, show_dot, muted=not tile.interactive))

    def status_table(self, snapshot: tuple[str, ...] | None = None) -> Group:
        snapshot = snapshot or self.dashboard_snapshot()
        (
            credential_status,
            credential_detail,
            credential_level,
            login_status,
            _monitor_status,
            _mode,
            delay_label,
            delay_range,
            purchase_delay_range,
            _purchase_rate,
            _purchase_detail,
            _silver_spent,
            _spend_detail,
            _runtime,
        ) = snapshot

        details = Table.grid(expand=True)
        details.add_column("Label", style="bold", no_wrap=True, width=13)
        details.add_column("Arrow", style="dim", no_wrap=True, width=3)
        details.add_column("Value", no_wrap=True, width=20)
        details.add_column("Detail", style="dim", no_wrap=True, overflow="ellipsis")
        details.add_row("Credentials", "->", self.status_text(credential_status, credential_level), credential_detail)
        details.add_row(
            "Session",
            "->",
            self.status_text(login_status, self.session_status_state()[2]),
            self.session_status_state()[1],
        )
        details.add_row("Polling", "->", self.status_text(delay_label, "info", show_dot=False), delay_range)
        details.add_row("Buy Delay", "->", self.status_text(purchase_delay_range, "info", show_dot=False), "Between buys")

        return Group(details)

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
                    self.refresh_dashboard_tiles(snapshot)
                    self._dashboard_snapshot = snapshot
                self.sync_event_log()
                self.refresh_modal_summaries()
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
        title.display = self.current_view not in {"dashboard", "settings"}

    def sync_event_log(self) -> None:
        self.refresh_event_log_filter_controls()
        events = tuple(self.task_manager.events_for_channel(self.event_log_mode))
        if events == self._rendered_events:
            return

        log = self.query_one("#event-log", RichLog)
        log.border_title = f"Event Log - {self.event_log_label()}"
        log.clear()
        if events:
            for event in events:
                log.write(event)
        else:
            log.write(f"No {self.event_log_label().lower()} events yet.")
        self._rendered_events = events

    def event_log_label(self) -> str:
        return "UI" if self.event_log_mode == "ui" else "Core"

    def refresh_event_log_filter_controls(self) -> None:
        for mode in ("core", "ui"):
            try:
                option = self.query_one(f"#log-filter-{mode}", LogFilterOption)
            except Exception:
                continue
            option.set_class(mode == self.event_log_mode, "log-filter-selected")

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

    def refresh_modal_tile(
        self,
        tile_id: str,
        title: str,
        value: str,
        detail: str,
        level: str = "info",
        show_dot: bool = False,
    ) -> None:
        try:
            tile = self.query_visible_one(f"#{tile_id}", Static)
        except Exception:
            return

        tile.border_title = title
        tile.update(
            self.tile_renderable(
                value,
                detail,
                level,
                show_dot=show_dot,
                subdued="modal-info-muted" in tile.classes,
            )
        )

    def modal_custom_delay_bounds(self) -> tuple[int, int] | None:
        try:
            low = int(self.query_visible_one("#custom-delay-min-input", Input).value.strip())
            high = int(self.query_visible_one("#custom-delay-max-input", Input).value.strip())
        except Exception:
            return None
        if low <= 0 or high <= 0:
            return None
        return low, high

    def matching_delay_choice(self, bounds: tuple[int, int] | None) -> str | None:
        if bounds is None:
            return None
        for key, (_label, preset_bounds) in self.task_manager.delay_choices.items():
            if tuple(preset_bounds) == bounds:
                return key
        return None

    def refresh_polling_preset_tiles(self) -> None:
        try:
            self.query_visible_one("#polling-recommendations")
        except Exception:
            return

        bounds = self.modal_custom_delay_bounds() or self.task_manager.current_delay_bounds()
        selected_key = self.matching_delay_choice(bounds)
        for key, (_label, (low, high)) in self.task_manager.delay_choices.items():
            try:
                tile = self.query_visible_one(f"#polling-preset-{key}", PollingPresetTile)
            except Exception:
                continue

            selected = key == selected_key
            if selected:
                tile.add_class("preset-selected")
            else:
                tile.remove_class("preset-selected")
            detail = "Recommended" if key == "2" else ""
            tile.update(self.tile_renderable(f"{low}-{high}s", detail, "orange" if selected else "info", False))

    def refresh_credentials_summary(self) -> None:
        try:
            summary = self.query_visible_one("#credentials-summary")
        except Exception:
            return

        state, detail, _, _, password = self.credential_state()
        pa_state, pa_detail, pa_level, pa_email, _pa_password = self.pa_credential_state()
        password_detail = "Stored in OS keyring" if password else "Not set"
        setup_complete = self.task_manager.steam_browser_profile_prepared
        setup_state = "Complete" if setup_complete else "Incomplete"
        setup_detail = "Ready for market login" if setup_complete else "Run Steam Setup once"
        setup_level = "success" if setup_complete else "warning"
        if isinstance(summary, Static):
            table = Table.grid(padding=(0, 2))
            table.add_column(style="bold")
            table.add_column()
            table.add_row("Login method", self.task_manager.account_mode_label())
            table.add_row("Email", detail)
            table.add_row("Password", password_detail)
            table.add_row("Status", state)
            table.add_row("Steam initial setup", setup_state)
            summary.update(table)
            return

        self.refresh_credentials_mode_controls()
        if self.selected_account_mode() == STEAM_BROWSER_MODE:
            self.refresh_modal_tile(
                "credential-action-tile",
                "Steam Initial Setup",
                setup_state,
                setup_detail,
                setup_level,
                True,
            )
        else:
            self.refresh_modal_tile(
                "credential-action-tile",
                "Pearl Abyss Account",
                pa_detail,
                "Click to update" if pa_email else "Click to enter credentials",
                pa_level,
                pa_email is not None,
            )

    def selected_account_mode(self) -> str:
        try:
            return str(self.query_visible_one("#account-mode-select", Select).value)
        except Exception:
            return self.task_manager.account_mode

    def refresh_credentials_mode_controls(self) -> None:
        try:
            selected_mode = self.selected_account_mode()
            steam_mode = selected_mode == STEAM_BROWSER_MODE
            note = self.query_visible_one("#credentials-mode-note", Static)
        except Exception:
            return

        if steam_mode:
            if self.task_manager.steam_browser_profile_prepared:
                note.update(
                    "Steam Account does not use saved email or password. Refresh Session opens a visible browser so you can complete Steam and Pearl Abyss login there."
                )
            else:
                note.update(
                    "Run Steam Setup once to build the app-owned browser profile from the Black Desert site. Refresh Session will use the market login after setup is saved."
                )
        else:
            note.update(
                "Pearl Abyss Account uses saved credentials when available. Refresh Session can also open a visible browser for manual login."
            )

        try:
            self.query_visible_one("#clear-credentials", Button).display = not steam_mode
        except Exception:
            pass

        try:
            setup_tile = self.query_visible_one("#credential-action-tile", SteamSetupTile)
            if steam_mode and not self.task_manager.steam_browser_profile_prepared:
                setup_tile.add_class("modal-info-clickable")
                setup_tile.remove_class("modal-info-muted")
            elif not steam_mode:
                setup_tile.add_class("modal-info-clickable")
                setup_tile.remove_class("modal-info-muted")
            else:
                setup_tile.remove_class("modal-info-clickable")
                setup_tile.add_class("modal-info-muted")
        except Exception:
            pass

    def refresh_pa_credentials_controls(self) -> None:
        try:
            email = self.query_visible_one("#email-input", Input).value.strip()
            password = self.query_visible_one("#password-input", Input).value
            save_button = self.query_visible_one("#save-pa-credentials", Button)
        except Exception:
            return

        save_button.disabled = not (email and password)
        if email and password:
            self.set_pa_credentials_warning("")

    def set_pa_credentials_warning(self, message: str) -> None:
        try:
            self.query_visible_one("#pa-credentials-warning", Static).update(message)
        except Exception:
            pass

    async def mount_settings(self, content: Container) -> None:
        settings_panel = Static(id="settings-summary", classes="settings-panel")
        settings_panel.border_title = "App Settings"
        await content.mount(settings_panel)

        session_debug = Vertical(id="session-debug-panel", classes="settings-panel")
        session_debug.border_title = "Session Debug"
        await content.mount(session_debug)
        await session_debug.mount(
            Static(
                "Clear the saved marketplace session cookies when login state looks stale or corrupted. "
                "This does not clear saved credentials.",
                classes="settings-note",
            )
        )
        await session_debug.mount(
            Horizontal(
                ModalAction("Clear Saved Session", "clear-saved-session"),
                id="settings-actions",
            )
        )
        self.refresh_settings_summary()

    def refresh_settings_summary(self) -> None:
        try:
            summary = self.query_visible_one("#settings-summary", Static)
        except Exception:
            return

        app_table = Table.grid(padding=(0, 2))
        app_table.add_column(style="bold")
        app_table.add_column()
        app_table.add_row("App", APP_TITLE)
        app_table.add_row("Version", APP_VERSION)
        app_table.add_row("Channel", APP_CHANNEL)
        app_table.add_row("Settings schema", str(SETTINGS_SCHEMA_VERSION))
        app_table.add_row("Launch mode", self.launch_mode)
        app_table.add_row("Theme", self.theme)

        settings_table = Table.grid(padding=(0, 2))
        settings_table.add_column(style="bold")
        settings_table.add_column()
        mode = "Buy mode" if self.task_manager.purchase_submission_enabled else "Watch only"
        settings_table.add_row("Session mode", self.task_manager.account_mode_label())
        settings_table.add_row("Session refresh", self.task_manager.account_mode_detail())
        settings_table.add_row("Mode", mode)
        settings_table.add_row(
            "Polling interval",
            f"{self.task_manager.current_delay_label()} ({self.task_manager.current_delay_range()})",
        )
        settings_table.add_row("Spend cap", format_compact_silver(self.task_manager.max_spend))
        settings_table.add_row("Tracked categories", "Outfits: male and female marketplace categories")
        summary.update(Group(app_table, Text(""), settings_table))

    def refresh_spend_summary(self) -> None:
        try:
            self.query_visible_one("#spend-summary")
        except Exception:
            return

        self.refresh_modal_tile("spend-cap-tile", "Cap", format_compact_silver(self.task_manager.max_spend), "This session")
        self.refresh_modal_tile(
            "spend-session-tile",
            "Session",
            format_compact_silver(self.task_manager.session_silver_spent),
            "Silver spent",
        )

    def refresh_polling_summary(self) -> None:
        try:
            self.query_visible_one("#polling-recommendations")
        except Exception:
            return

        self.refresh_polling_preset_tiles()

    def polling_status_detail(self) -> str:
        return f"{self.task_manager.current_delay_label()} ({self.task_manager.current_delay_range()})"

    def format_delay_seconds(self, value: float) -> str:
        return self.task_manager._format_seconds(value)

    def refresh_buy_delay_summary(self) -> None:
        try:
            self.query_visible_one("#buy-delay-summary")
        except Exception:
            return

        self.refresh_modal_tile(
            "buy-delay-current-tile",
            "Current",
            self.task_manager.purchase_delay_range(),
            "Between BuyItem requests",
        )

    def refresh_monitor_summary(self) -> None:
        try:
            self.query_visible_one("#monitor-summary")
        except Exception:
            return

        self.refresh_modal_tile(
            "monitor-status-tile",
            "Status",
            self.task_manager.monitor_status_label(),
            "Monitor",
            "success" if self.task_manager.monitor_running() else "error",
            True,
        )
        self.refresh_modal_tile(
            "monitor-mode-tile",
            "Mode",
            self.task_manager.monitor_mode_label(),
            "Purchase behavior",
        )
        self.refresh_modal_tile(
            "monitor-session-tile",
            "Session",
            self.session_status_state()[0].title(),
            self.session_status_state()[1],
            self.session_status_state()[2],
            True,
        )
        try:
            self.query_visible_one("#modal-start-monitor", Button).disabled = self.task_manager.monitor_running()
            self.query_visible_one("#modal-stop-monitor", Button).disabled = not self.task_manager.monitor_running()
        except Exception:
            pass

    def refresh_session_summary(self) -> None:
        try:
            self.query_visible_one("#session-summary")
        except Exception:
            return

        account = self.session_account_label()
        self.refresh_modal_tile("session-account-tile", "Account", account, self.task_manager.account_mode_label())
        try:
            credentials_row = self.query_visible_one("#session-credentials-row")
            refresh_button = self.query_visible_one("#refresh-session", Button)
        except Exception:
            return

        pa_mode = not self.task_manager.uses_steam_browser_session()
        if not pa_mode:
            setup_complete = self.task_manager.steam_browser_profile_prepared
            self.refresh_modal_tile(
                "session-credentials-tile",
                "Initial Setup",
                "Complete" if setup_complete else "Incomplete",
                "Ready for market login" if setup_complete else "Open Credentials to run setup",
                "success" if setup_complete else "warning",
                True,
            )
            refresh_button.disabled = False
            return

        _state, _detail, _level, email, password = self.pa_credential_state()
        credentials_ready = bool(email and password)
        self.refresh_modal_tile(
            "session-credentials-tile",
            "Credentials",
            "Set" if credentials_ready else "Optional",
            "Saved credential login" if credentials_ready else "Manual browser login available",
            "success" if credentials_ready else "info",
            True,
        )
        refresh_button.disabled = False

    def refresh_modal_summaries(self) -> None:
        self.refresh_credentials_summary()
        self.refresh_settings_summary()
        self.refresh_spend_summary()
        self.refresh_polling_summary()
        self.refresh_buy_delay_summary()
        self.refresh_monitor_summary()
        self.refresh_session_summary()

    async def mount_wallet(self, content: Container) -> None:
        wip_note = Static(
            "WIP: Marketplace Inventory is still being polished.",
            id="wallet-wip-note",
            classes="wip-note",
        )
        wip_note.border_title = "Work In Progress"
        await content.mount(wip_note)
        await content.mount(
            Horizontal(
                ModalAction("Refresh Inventory", "refresh-wallet"),
                id="wallet-actions",
            )
        )
        await content.mount(Static("Inventory data has not been loaded yet.", id="wallet-output", classes="panel"))

    async def mount_stats(self, content: Container) -> None:
        await content.mount(
            Horizontal(
                ModalAction("Refresh Stats", "refresh-stats"),
                id="stats-actions",
            )
        )
        await content.mount(Static("This Session", classes="stats-section-title"))
        await content.mount(
            Horizontal(
                Static(id="stats-session-detected", classes="stats-tile"),
                Static(id="stats-session-purchases", classes="stats-tile"),
                Static(id="stats-session-rate", classes="stats-tile"),
                Static(id="stats-session-spent", classes="stats-tile"),
                classes="stats-row",
            )
        )
        await content.mount(Static("Lifetime", classes="stats-section-title"))
        await content.mount(
            Horizontal(
                Static(id="stats-lifetime-purchases", classes="stats-tile"),
                Static(id="stats-lifetime-spent", classes="stats-tile"),
                classes="stats-row",
            )
        )
        self.refresh_stats()

    def refresh_stats_tile(
        self,
        tile_id: str,
        title: str,
        value: str,
        detail: str,
        level: str = "info",
        show_dot: bool = False,
    ) -> None:
        try:
            tile = self.query_one(f"#{tile_id}", Static)
        except Exception:
            return

        tile.border_title = title
        tile.update(self.tile_renderable(value, detail, level, show_dot=show_dot))

    def refresh_stats(self) -> None:
        self.task_manager.reload_lifetime_stats()
        self.refresh_stats_tile(
            "stats-session-detected",
            "Detected",
            str(self.task_manager.session_detected_outfits),
            "Outfits found",
        )
        self.refresh_stats_tile(
            "stats-session-purchases",
            "Bought",
            str(self.task_manager.session_successful_purchases),
            "This session",
            "success" if self.task_manager.session_successful_purchases else "info",
        )
        self.refresh_stats_tile(
            "stats-session-rate",
            "Success Rate",
            format_percent(
                self.task_manager.session_successful_purchases,
                self.task_manager.session_detected_outfits,
            ),
            f"{self.task_manager.session_successful_purchases}/{self.task_manager.session_detected_outfits} bought",
            self.purchase_rate_level(),
        )
        self.refresh_stats_tile(
            "stats-session-spent",
            "Silver Spent",
            format_compact_silver(self.task_manager.session_silver_spent),
            "This session",
        )
        self.refresh_stats_tile(
            "stats-lifetime-purchases",
            "Bought",
            str(self.task_manager.lifetime_successful_purchases),
            "All time",
            "success" if self.task_manager.lifetime_successful_purchases else "info",
        )
        self.refresh_stats_tile(
            "stats-lifetime-spent",
            "Silver Spent",
            format_compact_silver(self.task_manager.lifetime_silver_spent),
            "All time",
        )

    def on_modal_action_pressed(self, event: ModalAction.Pressed) -> None:
        if event.action.action_id not in {"refresh-stats", "refresh-wallet", "clear-saved-session", "clear-credentials"}:
            return

        event.stop()
        event.action.blur()
        if event.action.action_id == "refresh-stats":
            self.refresh_stats()
            self.set_status("Stats refreshed.", "info")
        elif event.action.action_id == "refresh-wallet":
            self.run_worker(self.refresh_wallet(), name="wallet-refresh", group="actions", exclusive=True)
        elif event.action.action_id == "clear-saved-session":
            self.run_worker(self.clear_saved_session(), name="clear-saved-session", group="actions", exclusive=True)
        else:
            self.run_worker(self.clear_saved_credentials(), name="clear-credentials", group="actions", exclusive=True)

    def on_log_filter_option_pressed(self, event: LogFilterOption.Pressed) -> None:
        event.stop()
        event.option.blur()
        if event.option.mode == self.event_log_mode:
            return
        try:
            self.event_log_mode = self.task_manager.set_event_log_view(event.option.mode)
        except ValueError:
            return
        self._rendered_events = None
        self.refresh_event_log_filter_controls()
        self.sync_event_log()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        event.button.blur()
        button_id = event.button.id
        if button_id == "save-pa-credentials":
            if await self.save_pa_credential_inputs():
                self.close_active_dashboard_modal()
        elif button_id == "clear-credentials":
            await self.clear_saved_credentials()
        elif button_id == "clear-saved-session":
            await self.clear_saved_session()
        elif button_id == "save-settings":
            await self.save_settings()
        elif button_id == "save-spend-cap":
            if self.apply_spend_cap_from_input("spend-cap-input"):
                self.refresh_modal_summaries()
                self.close_active_dashboard_modal()
        elif button_id == "save-polling":
            if self.save_polling_settings():
                self.refresh_modal_summaries()
                self.close_active_dashboard_modal()
        elif button_id == "save-buy-delay":
            if self.save_buy_delay_settings():
                self.refresh_modal_summaries()
                self.close_active_dashboard_modal()
        elif button_id == "modal-start-monitor":
            await self.start_monitor()
            self.refresh_modal_summaries()
        elif button_id == "modal-stop-monitor":
            await self.stop_monitor(close_modal=True)
        elif button_id == "refresh-session":
            self.push_screen(SessionRefreshConfirmScreen(), callback=self._handle_session_refresh_confirmation)
        elif button_id == "refresh-wallet":
            self.run_worker(self.refresh_wallet(), name="wallet-refresh", group="actions", exclusive=True)
        elif button_id == "refresh-stats":
            self.refresh_stats()
            self.set_status("Stats refreshed.", "info")
        elif button_id == "add-test-log":
            await self.add_test_log()
        elif button_id == "toggle-test-session":
            await self.toggle_test_session()
        elif button_id == "toggle-auto-reauth":
            await self.toggle_test_steam_auto_reauth()
        elif button_id == "expire-test-session":
            await self.expire_test_session()
        elif button_id == "run-reauth-check":
            await self.run_test_reauthentication_check()
        elif button_id == "prepare-steam-profile":
            self.run_worker(
                self.prepare_steam_browser_profile(),
                name="prepare-steam-profile",
                group="actions",
                exclusive=True,
            )
        elif button_id == "open-blank-browser":
            if self._debug_action_allowed():
                self.run_worker(
                    self.open_blank_browser_diagnostic(),
                    name="blank-browser-diagnostic",
                    group="actions",
                    exclusive=True,
                )
        elif button_id == "reset-steam-setup":
            await self.reset_test_steam_setup_status()
        elif button_id == "clear-browser-cookies":
            if self._debug_action_allowed():
                self.run_worker(
                    self.clear_test_browser_cookies(),
                    name="clear-browser-cookies",
                    group="actions",
                    exclusive=True,
                )
        elif button_id == "start-test-monitor":
            await self.start_single_item_test_monitor()
        elif button_id == "start-test-buy":
            await self.start_single_item_test_monitor(allow_purchase=True)
        elif button_id == "stop-test-monitor":
            await self.stop_single_item_test_monitor()
        elif button_id == "fake-detection":
            await self.fake_outfit_detection()
        elif button_id == "fake-buy-success":
            await self.fake_buy_success()

    async def on_dashboard_tile_pressed(self, event: DashboardTile.Pressed) -> None:
        event.stop()
        if not event.tile.interactive:
            return

        tile_key = event.tile.tile_key
        if tile_key == "monitor":
            self.push_screen(MonitorModal())
        elif tile_key == "spent":
            self.push_screen(SpendCapModal())
        elif tile_key == "credentials":
            self.push_screen(CredentialsModal())
        elif tile_key == "session":
            self.push_screen(SessionModal())
        elif tile_key == "polling":
            self.push_screen(PollingModal())
        elif tile_key == "buy-delay":
            self.push_screen(BuyDelayModal())
        self.call_after_refresh(self.refresh_modal_summaries)

    def _handle_session_refresh_confirmation(self, confirmed: bool) -> None:
        if confirmed:
            self.close_dashboard_modals()
            self.run_worker(self.login_refresh(), name="login-refresh", group="actions", exclusive=True)

    def on_polling_preset_tile_pressed(self, event: PollingPresetTile.Pressed) -> None:
        event.stop()
        low, high = self.task_manager.delay_choices[event.preset.preset_key][1]
        try:
            self.query_visible_one("#custom-delay-min-input", Input).value = str(low)
            self.query_visible_one("#custom-delay-max-input", Input).value = str(high)
        except Exception:
            return
        self.refresh_polling_preset_tiles()

    def on_credential_action_tile_pressed(self, event: CredentialActionTile.Pressed) -> None:
        event.stop()
        if self.selected_account_mode() != STEAM_BROWSER_MODE:
            self.push_screen(PACredentialsModal())
            self.call_after_refresh(self.refresh_pa_credentials_controls)
            return

        self.run_worker(
            self.prepare_steam_browser_profile(),
            name="prepare-steam-profile",
            group="actions",
            exclusive=True,
        )

    def on_steam_setup_tile_pressed(self, event: SteamSetupTile.Pressed) -> None:
        self.on_credential_action_tile_pressed(event)

    async def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "account-mode-select":
            await self.apply_account_mode_selection(event.value)
            self.refresh_credentials_summary()
            return

        if event.select.id != "delay-select":
            return
        self.apply_delay_choice(event.value)

    async def apply_account_mode_selection(self, account_mode: object) -> None:
        try:
            normalized_mode = str(account_mode)
            if normalized_mode == self.task_manager.account_mode:
                return
            await self.task_manager.change_account_mode(normalized_mode)
        except ValueError:
            self.set_status("Select a valid login method.", "warning")
            return

        if normalized_mode == PA_CREDENTIALS_MODE:
            _state, _detail, _level, email, password = self.pa_credential_state()
            if email and password:
                self.api_handler.email = email
                self.api_handler.password = password

        self.sync_mode_switches(False)
        self.set_status(f"Login method set to {self.task_manager.account_mode_label()}.")
        self.refresh_settings_summary()
        self.refresh_live_widgets()

    async def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id != "buy-mode-switch":
            return
        await self.apply_purchase_mode(bool(event.value), source_switch_id=event.switch.id)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id in {
            "spend-cap-input",
            "custom-delay-min-input",
            "custom-delay-max-input",
            "purchase-delay-min-input",
            "purchase-delay-max-input",
        }:
            event.stop()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id in {"custom-delay-min-input", "custom-delay-max-input"}:
            self.refresh_polling_preset_tiles()
        elif event.input.id in {"purchase-delay-min-input", "purchase-delay-max-input"}:
            return
        elif event.input.id == "spend-cap-input":
            return
        elif event.input.id in {"email-input", "password-input"}:
            self.refresh_pa_credentials_controls()

    def apply_delay_choice(self, delay: object) -> None:
        delay = str(delay)
        if delay == "custom":
            if delay == self.task_manager.delay:
                return

            self.task_manager.set_custom_delay_choice()
            self.set_status(f"Polling set to {self.polling_status_detail()}.", "info")
            self.refresh_settings_summary()
            self.refresh_live_widgets()
            return

        if delay not in self.task_manager.delay_choices or delay == self.task_manager.delay:
            return

        self.task_manager.set_delay_choice(delay)
        self.set_status(f"Polling set to {self.polling_status_detail()}.", "info")
        self.refresh_settings_summary()
        self.refresh_live_widgets()

    def apply_custom_delay_from_inputs(self, log_status: bool = True) -> bool:
        try:
            min_input = self.query_visible_one("#custom-delay-min-input", Input)
            max_input = self.query_visible_one("#custom-delay-max-input", Input)
        except Exception:
            return False

        try:
            self.task_manager.set_custom_delay_range(min_input.value.strip(), max_input.value.strip())
        except (TypeError, ValueError):
            self.set_status(
                "Custom polling range must use positive seconds with min less than or equal to max.",
                "warning",
            )
            return False

        if log_status:
            self.set_status(f"Polling set to {self.polling_status_detail()}.", "info")
        self.refresh_settings_summary()
        self.refresh_live_widgets()
        return True

    def save_polling_settings(self) -> bool:
        if not self.apply_custom_delay_from_inputs(log_status=False):
            return False

        self.set_status(f"Polling settings saved: {self.polling_status_detail()}.", "success")
        return True

    def apply_purchase_delay_from_inputs(self, log_status: bool = True) -> bool:
        try:
            min_input = self.query_visible_one("#purchase-delay-min-input", Input)
            max_input = self.query_visible_one("#purchase-delay-max-input", Input)
        except Exception:
            return False

        try:
            self.task_manager.set_purchase_delay_range(min_input.value.strip(), max_input.value.strip())
        except (TypeError, ValueError):
            self.set_status(
                "Buy delay must use non-negative seconds with min less than or equal to max.",
                "warning",
            )
            return False

        if log_status:
            self.set_status(f"Buy delay set to {self.task_manager.purchase_delay_range()}.", "info")
        self.refresh_live_widgets()
        return True

    def save_buy_delay_settings(self) -> bool:
        if not self.apply_purchase_delay_from_inputs(log_status=False):
            return False

        self.set_status(f"Buy delay saved: {self.task_manager.purchase_delay_range()}.", "success")
        return True

    async def apply_purchase_mode(self, enabled: bool, source_switch_id: str | None = None) -> None:
        if self._syncing_controls:
            return

        if enabled == self.task_manager.purchase_submission_enabled:
            return

        if not enabled:
            self.task_manager.set_purchase_submission_enabled(False)
            self.set_status("Mode set to watch only.", "info")
            self.sync_mode_switches(False, except_id=source_switch_id)
            self.refresh_settings_summary()
            self.refresh_live_widgets()
            return

        if self.task_manager.checker_enabled:
            if not self.api_handler.login_status:
                self.set_status(
                    "Login required before enabling buy mode. Login or refresh the marketplace session first.",
                    "warning",
                )
                self.sync_mode_switches(False)
                self.refresh_live_widgets()
                return

            self.push_screen(
                ConfirmBuyModeScreen(
                    account=self.session_account_label(),
                    polling=f"{self.task_manager.current_delay_label()} ({self.task_manager.current_delay_range()})",
                    spend_cap=format_compact_silver(self.task_manager.max_spend),
                    buy_delay=self.task_manager.purchase_delay_range(),
                ),
                callback=self._handle_running_buy_mode_confirmation,
            )
            return

        if self.task_manager.single_item_test_checker_enabled:
            self.set_status("Single-item test monitor is running. Stop it before changing buy mode.", "warning")
            self.sync_mode_switches(False)
            self.refresh_live_widgets()
            return

        self.task_manager.set_purchase_submission_enabled(True)
        self.set_status("Mode set to buy mode. Starting the monitor will ask for confirmation.", "warning")
        self.sync_mode_switches(True, except_id=source_switch_id)
        self.refresh_settings_summary()
        self.refresh_live_widgets()

    def _handle_running_buy_mode_confirmation(self, confirmed: bool) -> None:
        self.task_manager.set_purchase_submission_enabled(bool(confirmed))
        if confirmed:
            self.set_status("Buy mode enabled for the running monitor.", "warning")
        else:
            self.set_status("Buy mode canceled. Monitor remains watch only.", "info")
        self.sync_mode_switches(self.task_manager.purchase_submission_enabled)
        self.refresh_settings_summary()
        self.refresh_live_widgets()

    def sync_mode_switches(self, value: bool, except_id: str | None = None) -> None:
        self._syncing_controls = True
        try:
            for switch_id in ("buy-mode-switch",):
                if switch_id == except_id:
                    continue
                try:
                    self.query_visible_one(f"#{switch_id}", Switch).value = value
                except Exception:
                    pass
        finally:
            self._syncing_controls = False

    def apply_spend_cap_from_input(self, input_id: str) -> bool:
        try:
            spend_input = self.query_visible_one(f"#{input_id}", Input)
        except Exception:
            return False

        spend_value = spend_input.value.strip() or "0"
        try:
            spend_cap = int(spend_value)
            if spend_cap < 0:
                raise ValueError
        except ValueError:
            self.set_status("Spend cap must be 0 or a positive integer.", "warning")
            return False

        self.set_spend_cap(spend_cap)
        return True

    def set_spend_cap(self, spend_cap: int) -> None:
        self.task_manager.set_spend_cap(spend_cap)
        self.sync_spend_cap_inputs()
        self.set_status(f"Spend cap set to {format_compact_silver(self.task_manager.max_spend)}.", "info")
        self.refresh_settings_summary()
        self.refresh_live_widgets()

    def sync_spend_cap_inputs(self) -> None:
        value = str(self.task_manager.max_spend or 0)
        for input_id in ("spend-cap-input",):
            try:
                self.query_visible_one(f"#{input_id}", Input).value = value
            except Exception:
                pass

    def _debug_action_allowed(self) -> bool:
        if self.is_test_mode:
            return True

        self.set_status("Debug actions are only available in test mode.", "warning")
        return False

    async def add_test_log(self) -> None:
        if not self._debug_action_allowed():
            return

        message, level = random.choice(TEST_LOG_MESSAGES)
        self.task_manager.add_event(message, level)
        self.set_status("Synthetic event added.")
        await self.return_to_dashboard()

    async def toggle_test_session(self) -> None:
        if not self._debug_action_allowed():
            return

        if self.task_manager.single_item_test_checker_enabled:
            self.set_status("Stop the single-item test monitor before changing simulated session state.", "warning")
            await self.return_to_dashboard()
            return

        enabled = not self.is_simulated_session
        self.task_manager.set_simulated_session(enabled)
        if enabled:
            self.set_status(
                "Test session marked valid. Buy mode will use simulated purchase responses.",
                "success",
            )
        else:
            self.sync_mode_switches(False)
            self.set_status("Test session marked invalid. Buy mode returned to watch only.", "warning")
        self.refresh_modal_summaries()
        await self.return_to_dashboard()

    async def toggle_test_steam_auto_reauth(self) -> None:
        if not self._debug_action_allowed():
            return

        enabled = self.task_manager.debug_toggle_steam_auto_reauth()
        if enabled is None:
            self.set_status("Select Steam Account before toggling automatic re-authentication.", "warning")
        elif enabled:
            self.set_status("Steam automatic re-authentication enabled for this test run.", "success")
        else:
            self.set_status("Steam automatic re-authentication disabled for this test run.", "warning")
        self.refresh_modal_summaries()
        await self.return_to_dashboard()

    async def expire_test_session(self) -> None:
        if not self._debug_action_allowed():
            return

        if self.task_manager.debug_invalidate_marketplace_session():
            self.refresh_modal_summaries()
        await self.return_to_dashboard()

    async def run_test_reauthentication_check(self) -> None:
        if not self._debug_action_allowed():
            return

        recovered = await self.task_manager.debug_run_reauthentication_check()
        if recovered:
            self.set_status("Test re-authentication check succeeded.")
        elif self.task_manager.uses_steam_browser_session():
            self.set_status("Steam Account refresh required after test re-authentication check.")
        else:
            self.set_status("Test re-authentication check failed.")
        self.refresh_modal_summaries()
        await self.return_to_dashboard()

    async def open_blank_browser_diagnostic(self) -> None:
        self.set_status("Opening blank Chrome diagnostic browser.")
        opened = await self.task_manager.debug_open_blank_browser_diagnostic()
        if opened:
            self.set_status("Blank Chrome diagnostic browser closed.")
        else:
            self.set_status("Blank Chrome diagnostic browser failed.")
        self.refresh_live_widgets()

    async def reset_test_steam_setup_status(self) -> None:
        if not self._debug_action_allowed():
            return

        if self.task_manager.debug_clear_steam_initial_setup_status():
            self.set_status("Initial Steam setup status reset.", "warning")
            self.refresh_credentials_summary()
            self.refresh_settings_summary()
            self.refresh_live_widgets()
        else:
            self.set_status("Initial Steam setup status reset failed.", "warning")

    async def clear_test_browser_cookies(self) -> None:
        if not self._debug_action_allowed():
            return

        cleared = await self.task_manager.debug_clear_steam_browser_cookies()
        if cleared:
            self.set_status("Browser cookies cleared from the Steam profile.", "warning")
        else:
            self.set_status("Browser cookie clear failed.", "warning")

    async def start_single_item_test_monitor(self, allow_purchase: bool = False) -> None:
        if not self._debug_action_allowed():
            return

        item_name = SINGLE_ITEM_TEST_TARGET["name"]
        if self.task_manager.single_item_test_checker_enabled:
            self.set_status("Single-item test monitor already running; no additional task started.", "info")
            await self.return_to_dashboard()
            return

        if self.task_manager.checker_enabled:
            self.set_status("Stop the normal monitor before starting the single-item test monitor.", "warning")
            await self.return_to_dashboard()
            return

        if allow_purchase:
            if self.is_simulated_session:
                self.set_status(
                    "Disable the simulated test session before starting the live single-item buy test.",
                    "warning",
                )
                await self.return_to_dashboard()
                return

            if not self.api_handler.login_status:
                self.set_status(
                    "Login required before starting the single-item buy test. Refresh the marketplace session first.",
                    "warning",
                )
                await self.return_to_dashboard()
                return

            self.push_screen(
                ConfirmBuyModeScreen(
                    account=self.session_account_label(),
                    polling=f"{self.task_manager.current_delay_label()} ({self.task_manager.current_delay_range()})",
                    spend_cap=format_compact_silver(self.task_manager.max_spend),
                    buy_delay=self.task_manager.purchase_delay_range(),
                ),
                callback=self._handle_single_item_test_buy_confirmation,
            )
            return

        await self._start_single_item_test_monitor_now(allow_purchase=False)

    def _handle_single_item_test_buy_confirmation(self, confirmed: bool) -> None:
        if not confirmed:
            self.set_status("Single-item buy test canceled.", "info")
            return
        self.run_worker(
            self._start_single_item_test_monitor_now(allow_purchase=True),
            name="start-single-item-buy-test",
            group="actions",
            exclusive=True,
        )

    async def _start_single_item_test_monitor_now(self, allow_purchase: bool = False) -> None:
        item_name = SINGLE_ITEM_TEST_TARGET["name"]
        started = await self.task_manager.start_single_item_test_checker(allow_purchase=allow_purchase)
        if started:
            if allow_purchase:
                self.set_status(
                    f"Single-item buy test started for {item_name}. Public detection uses the normal buy pipeline.",
                    "warning",
                )
            else:
                self.set_status(
                    f"Single-item test monitor started for {item_name}. Public scan only; live buy calls are disabled.",
                    "warning",
                )
        elif self.task_manager.single_item_test_checker_enabled:
            self.set_status("Single-item test monitor already running; no additional task started.", "info")
        else:
            self.set_status("Single-item test monitor did not start.", "warning")
        await self.return_to_dashboard()

    async def stop_single_item_test_monitor(self) -> None:
        if not self._debug_action_allowed():
            return

        was_running = await self.task_manager.stop_single_item_test_checker()
        if was_running:
            self.set_status("Single-item test monitor stopped.", "info")
        else:
            self.set_status("Single-item test monitor already stopped.", "info")
        await self.return_to_dashboard()

    async def fake_outfit_detection(self) -> None:
        if not self._debug_action_allowed():
            return

        await self.task_manager.debug_fake_outfit_detection()
        self.set_status("Fake detection processed through watch-only path.")
        await self.return_to_dashboard()

    async def fake_buy_success(self) -> None:
        if not self._debug_action_allowed():
            return

        await self.task_manager.debug_simulate_purchase_success()
        self.set_status("Fake detection and purchase recorded.")
        await self.return_to_dashboard()

    async def prepare_steam_browser_profile(self) -> None:
        try:
            account_mode = self.selected_account_mode()
        except ValueError:
            self.set_status("Select Steam Account before running setup.", "warning")
            return

        if account_mode != STEAM_BROWSER_MODE:
            self.set_status("Select Steam Account before running setup.", "warning")
            return

        self.set_status("Opening initial Steam browser setup.")
        prepared = await self.task_manager.prepare_steam_browser_profile(allow_inactive_mode=True)
        if prepared:
            self.set_status("Initial Steam setup saved. Refresh Session can now use the market login.")
        else:
            self.set_status("Initial Steam setup did not complete.")
        self.refresh_credentials_summary()
        self.refresh_settings_summary()
        self.refresh_live_widgets()

    async def return_to_dashboard(self) -> None:
        if self.current_view != "dashboard":
            await self.show_view("dashboard")
            return
        self.refresh_live_widgets()

    async def save_pa_credential_inputs(self) -> bool:
        email = self.query_visible_one("#email-input", Input).value.strip()
        password = self.query_visible_one("#password-input", Input).value
        _saved_state, _saved_detail, _saved_level, saved_email, saved_password = self.pa_credential_state()
        if not (email and password):
            self.refresh_pa_credentials_controls()
            return False
        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            self.set_pa_credentials_warning("Enter a valid email address.")
            return False
        saved_email_matches = bool(saved_email and saved_email.strip().lower() == email.strip().lower())

        previous_email = self.api_handler.email
        session_identity_changed = bool(
            self.api_handler.login_status
            and (not previous_email or previous_email.strip().lower() != email.strip().lower())
        )
        self.api_handler.email = email
        self.api_handler.password = password
        try:
            if password == saved_password and saved_email_matches:
                save_credentials(email)
            else:
                save_credentials(email, password)
        except CredentialStoreError as exc:
            self.set_pa_credentials_warning(f"Unable to save credentials: {exc}")
            return False

        mode_changed = await self.task_manager.change_account_mode(PA_CREDENTIALS_MODE)
        if session_identity_changed and not mode_changed:
            await self.task_manager.reset_authentication_context("Credentials changed")
        self.sync_mode_switches(False)
        self.query_visible_one("#password-input", Input).value = ""
        self.set_status(f"Credentials saved: {self.task_manager.account_mode_label()}.", "success")
        self.refresh_credentials_summary()
        self.refresh_settings_summary()
        self.refresh_live_widgets()
        return True

    async def clear_saved_credentials(self) -> None:
        try:
            clear_credentials()
        except CredentialStoreError as exc:
            self.task_manager.add_event(f"Unable to clear credentials: {exc}", "error")
            self.set_status("Unable to clear saved credentials.")
            return

        self.api_handler.email = None
        self.api_handler.password = None
        for input_id in ("email-input", "password-input"):
            try:
                self.query_visible_one(f"#{input_id}", Input).value = ""
            except Exception:
                pass
        self.set_status("Saved credentials cleared.", "info")
        self.refresh_credentials_summary()
        self.refresh_settings_summary()
        self.refresh_live_widgets()

    async def clear_saved_session(self) -> None:
        cleared_now = await self.task_manager.reset_authentication_context("Manual session reset")
        self.sync_mode_switches(False)
        if cleared_now:
            self.set_status("Saved marketplace session cleared. Refresh Session to log in again.", "warning")
        else:
            self.set_status("Session reset queued until the current purchase chain finishes.", "warning")
        self.refresh_settings_summary()
        self.refresh_live_widgets()

    async def save_settings(self) -> None:
        try:
            account_mode = self.query_visible_one("#account-mode-select", Select).value
        except Exception:
            self.set_status("Settings are not available.", "warning")
            return

        try:
            normalized_mode = self.task_manager.set_account_mode(str(account_mode))
        except ValueError:
            self.set_status("Select a valid session mode.", "warning")
            return

        if normalized_mode == STEAM_BROWSER_MODE and self.task_manager.purchase_submission_enabled:
            self.task_manager.set_purchase_submission_enabled(False)
            self.sync_mode_switches(False)

        self.set_status(f"Settings saved: {self.task_manager.account_mode_label()}.", "success")
        self.refresh_settings_summary()
        self.refresh_live_widgets()

    async def login_refresh(self) -> None:
        self.task_manager.add_event("Fetching session status...", "info")
        self.set_status("Fetching session status...")
        await self.task_manager.login()
        self.set_status("Login check complete.")
        self.refresh_live_widgets()

    async def start_monitor(self) -> None:
        if self.task_manager.single_item_test_checker_enabled:
            self.set_status("Single-item test monitor is running. Stop it before starting the normal monitor.", "warning")
            self.refresh_live_widgets()
            return

        if self.task_manager.checker_enabled:
            mode = "buy mode" if self.task_manager.purchase_submission_enabled else "watch-only mode"
            self.set_status(f"Monitor already running in {mode}; no additional monitor task started.", "info")
            self.refresh_live_widgets()
            return

        if self.task_manager.purchase_submission_enabled and not self.api_handler.login_status:
            if self.task_manager.uses_steam_browser_session():
                self.set_status(
                    "Steam Account refresh required before starting buy mode. Refresh Session first.",
                    "warning",
                )
                self.refresh_live_widgets()
                return

            self.set_status(
                "Login required before starting buy mode. Login or refresh the marketplace session before starting the monitor.",
                "warning",
            )
            self.refresh_live_widgets()
            return

        if self.task_manager.purchase_submission_enabled:
            self.push_screen(
                ConfirmBuyModeScreen(
                    account=self.session_account_label(),
                    polling=f"{self.task_manager.current_delay_label()} ({self.task_manager.current_delay_range()})",
                    spend_cap=format_compact_silver(self.task_manager.max_spend),
                    buy_delay=self.task_manager.purchase_delay_range(),
                ),
                callback=self._handle_buy_mode_confirmation,
            )
            return

        await self._start_monitor_now()

    def _handle_buy_mode_confirmation(self, confirmed: bool) -> None:
        if not confirmed:
            self.set_status("Buy mode start canceled.", "info")
            return
        self.run_worker(self._start_monitor_now(), name="start-buy-mode", group="actions", exclusive=True)

    async def _start_monitor_now(self) -> None:
        mode = "buy mode" if self.task_manager.purchase_submission_enabled else "watch-only mode"
        started = await self.task_manager.start_checker()
        if started:
            self.set_status(f"Monitor started in {mode}.", "success")
            self.close_dashboard_modals()
        elif self.task_manager.single_item_test_checker_enabled:
            self.set_status("Single-item test monitor is running. Stop it before starting the normal monitor.", "warning")
        elif self.task_manager.checker_enabled:
            self.set_status(f"Monitor already running in {mode}; no additional monitor task started.", "info")
        else:
            self.set_status(f"Monitor did not start in {mode}.", "warning")
        await self.show_view("dashboard")

    async def refresh_wallet(self) -> None:
        self.set_status("Loading marketplace inventory...")
        try:
            response = await self.api_handler.get_mp_inventory()
            silver_balance = marketplace_silver_balance(response)
        except Exception as exc:
            self.task_manager.add_event(f"Inventory lookup failed: {exc}", "error")
            self.set_status("Inventory lookup failed.")
            try:
                self.query_one("#wallet-output", Static).update(str(exc))
            except Exception:
                pass
            return

        summary = Table.grid(padding=(0, 2))
        summary.add_column(style="bold")
        summary.add_column()
        summary.add_row("Silver", format_compact_silver(silver_balance) if silver_balance is not None else "Not found")
        summary.add_row("Value Pack", "Active" if response.get("useValuePackage") else "Inactive")
        if response.get("totalWeight") is not None and response.get("maxWeight") is not None:
            summary.add_row("Weight", f"{response.get('totalWeight')}/{response.get('maxWeight')}")

        self.query_one("#wallet-output", Static).update(Group(summary, JSON.from_data(response)))
        if silver_balance is not None:
            self.set_status(f"Inventory loaded: {format_compact_silver(silver_balance)}.", "success")
        else:
            self.set_status("Inventory loaded.", "success")

    def action_show_dashboard(self) -> None:
        self.run_worker(self.show_view("dashboard"), name="show-dashboard", group="navigation", exclusive=True)

    async def action_quit_app(self) -> None:
        await self.task_manager.stop_checker()
        await self.task_manager.stop_single_item_test_checker()
        await self.task_manager.stop_login_status_checker()
        self.api_handler.save_session()
        self.exit()

