from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, Switch

from bdo_marketplace_tools.storage.app_settings import ACCOUNT_MODE_LABELS
from bdo_marketplace_tools.ui.styles import MODAL_CSS
from bdo_marketplace_tools.ui.widgets import ModalAction, PollingPresetTile, SteamSetupTile


class DashboardModalScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close_modal", "Close", show=False)]
    CSS = MODAL_CSS

    def close_modal(self) -> None:
        self.dismiss(None)

    def action_close_modal(self) -> None:
        self.close_modal()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.button.blur()
        if event.button.id in {"close-modal", "cancel-modal"}:
            event.stop()
            self.close_modal()



class ConfirmBuyModeScreen(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]
    CSS = DashboardModalScreen.CSS

    def __init__(self, account: str, polling: str, spend_cap: str, buy_delay: str) -> None:
        super().__init__()
        self.account = account
        self.polling = polling
        self.spend_cap = spend_cap
        self.buy_delay = buy_delay

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog", classes="modal-card") as dialog:
            dialog.border_title = "Confirm Buy Mode"
            yield Static(f"Account: {self.account}")
            yield Static("Mode: Buy mode")
            yield Static(f"Polling interval: {self.polling}")
            yield Static(f"Spend cap: {self.spend_cap}")
            yield Static(f"Buy delay: {self.buy_delay}")
            with Horizontal(id="confirm-actions", classes="modal-actions"):
                yield ModalAction("Start Buy Mode", "confirm-start")
                yield ModalAction("Cancel", "confirm-cancel")

    def on_modal_action_pressed(self, event: ModalAction.Pressed) -> None:
        self.dismiss(event.action.action_id == "confirm-start")

    def action_cancel(self) -> None:
        self.dismiss(False)


class MonitorModal(DashboardModalScreen):
    def compose(self) -> ComposeResult:
        app = self.app
        with Vertical(classes="modal-card") as dialog:
            dialog.border_title = "Monitor"
            with Horizontal(id="monitor-summary", classes="modal-summary-row"):
                yield Static(id="monitor-status-tile", classes="modal-info-tile modal-info-muted")
                yield Static(id="monitor-mode-tile", classes="modal-info-tile modal-info-muted")
                yield Static(id="monitor-session-tile", classes="modal-info-tile modal-info-muted")
            yield Static(
                "Buy mode requires an online marketplace session. If the session is offline, refresh Session from the dashboard before starting buy mode.",
                classes="modal-note",
            )
            with Horizontal(classes="modal-row"):
                yield Label("Buy mode")
                yield Switch(value=app.task_manager.purchase_submission_enabled, id="buy-mode-switch")
            with Horizontal(classes="modal-actions"):
                yield Button("Start", id="modal-start-monitor", variant="primary", disabled=app.task_manager.monitor_running())
                yield Button("Stop", id="modal-stop-monitor", variant="warning", disabled=not app.task_manager.monitor_running())
                yield Button("Close", id="close-modal")


class SpendCapModal(DashboardModalScreen):
    def compose(self) -> ComposeResult:
        app = self.app
        with Vertical(classes="modal-card") as dialog:
            dialog.border_title = "Spent"
            yield Static("Silver Spend Cap", classes="modal-heading")
            with Horizontal(id="spend-summary", classes="modal-summary-row"):
                yield Static(id="spend-cap-tile", classes="modal-info-tile modal-info-muted")
                yield Static(id="spend-session-tile", classes="modal-info-tile modal-info-muted")
            yield Label("Spend cap in silver")
            yield Input(
                value=str(app.task_manager.max_spend or 0),
                type="integer",
                placeholder="0 for no cap",
                id="spend-cap-input",
            )
            with Horizontal(classes="modal-actions"):
                yield Button("Save", id="save-spend-cap", variant="primary")
                yield Button("Close", id="close-modal")


class PollingModal(DashboardModalScreen):
    def compose(self) -> ComposeResult:
        app = self.app
        low, high = app.task_manager.current_delay_bounds()
        with Vertical(classes="modal-card") as dialog:
            dialog.border_title = "Polling"
            yield Static("Presets", classes="modal-section-title")
            yield Static(
                "Polling controls how often the app checks the marketplace for new listings. Slower polling is calmer; faster polling checks more often.",
                classes="modal-note",
            )
            with Horizontal(id="polling-recommendations", classes="modal-summary-row"):
                yield PollingPresetTile("1", "Fast")
                yield PollingPresetTile("2", "Balanced")
                yield PollingPresetTile("3", "Slow")
            with Horizontal(classes="modal-row"):
                yield Label("Custom min")
                yield Input(value=str(low), type="integer", placeholder="Seconds", id="custom-delay-min-input")
            with Horizontal(classes="modal-row"):
                yield Label("Custom max")
                yield Input(value=str(high), type="integer", placeholder="Seconds", id="custom-delay-max-input")
            with Horizontal(classes="modal-actions"):
                yield Button("Save", id="save-polling", variant="primary")
                yield Button("Close", id="close-modal")


class BuyDelayModal(DashboardModalScreen):
    def compose(self) -> ComposeResult:
        app = self.app
        low, high = app.task_manager.purchase_delay_bounds
        with Vertical(classes="modal-card") as dialog:
            dialog.border_title = "Buy Delay"
            with Horizontal(id="buy-delay-summary", classes="modal-summary-row"):
                yield Static(id="buy-delay-current-tile", classes="modal-info-tile modal-info-muted")
            yield Static(
                "When a scan finds multiple buyable items, this waits a random amount of time between each purchase attempt. It does not change how often the app scans.",
                classes="modal-note",
            )
            with Horizontal(classes="modal-row"):
                yield Label("Delay min")
                yield Input(
                    value=app.format_delay_seconds(low),
                    type="number",
                    placeholder="Seconds",
                    id="purchase-delay-min-input",
                )
            with Horizontal(classes="modal-row"):
                yield Label("Delay max")
                yield Input(
                    value=app.format_delay_seconds(high),
                    type="number",
                    placeholder="Seconds",
                    id="purchase-delay-max-input",
                )
            with Horizontal(classes="modal-actions"):
                yield Button("Save", id="save-buy-delay", variant="primary")
                yield Button("Close", id="close-modal")


class CredentialsModal(DashboardModalScreen):
    def compose(self) -> ComposeResult:
        app = self.app
        mode_options = [(label, value) for value, label in ACCOUNT_MODE_LABELS.items()]
        with Vertical(classes="modal-card") as dialog:
            dialog.border_title = "Credentials"
            yield Label("Login method")
            yield Select(
                mode_options,
                value=app.task_manager.account_mode,
                id="account-mode-select",
            )
            yield Static(id="credentials-mode-note", classes="modal-note")
            with Horizontal(id="credentials-summary", classes="modal-summary-row"):
                yield SteamSetupTile()
            with Horizontal(classes="modal-actions"):
                yield Button("Clear PA Account", id="clear-credentials", variant="error")
                yield Button("Close", id="close-modal")


class PACredentialsModal(DashboardModalScreen):
    def compose(self) -> ComposeResult:
        app = self.app
        _, _, _, email, _ = app.pa_credential_state()
        with Vertical(classes="modal-card") as dialog:
            dialog.border_title = "Pearl Abyss Account"
            yield Static(
                "Pearl Abyss Account uses your saved email and OS keyring password when the app refreshes the marketplace session.",
                classes="modal-note",
            )
            yield Label("Email", id="credentials-email-label")
            yield Input(value=email or "", placeholder="account@example.com", id="email-input")
            yield Label("Password", id="credentials-password-label")
            yield Input(password=True, placeholder="Stored in OS keyring", id="password-input")
            yield Static("", id="pa-credentials-warning", classes="modal-warning")
            with Horizontal(classes="modal-actions"):
                yield Button("Save", id="save-pa-credentials", variant="primary", disabled=True)
                yield Button("Close", id="close-modal")


class SessionModal(DashboardModalScreen):
    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-card") as dialog:
            dialog.border_title = "Session"
            yield Static("Marketplace Session", classes="modal-heading")
            with Horizontal(id="session-summary", classes="modal-summary-row"):
                yield Static(id="session-account-tile", classes="modal-info-tile modal-info-muted modal-info-wide")
            with Horizontal(id="session-credentials-row", classes="modal-summary-row"):
                yield Static(id="session-credentials-tile", classes="modal-info-tile modal-info-muted modal-info-wide")
            with Horizontal(classes="modal-actions"):
                refresh_button = Button("Refresh Session", id="refresh-session")
                refresh_button.can_focus = False
                yield refresh_button
                close_button = Button("Close", id="close-modal")
                close_button.can_focus = False
                yield close_button


class SessionRefreshConfirmScreen(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]
    CSS = DashboardModalScreen.CSS

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-card") as dialog:
            dialog.border_title = "Refresh Session"
            yield Static("Refresh the marketplace session now?")
            with Horizontal(classes="modal-actions"):
                yield ModalAction("Refresh", "confirm-refresh-session")
                yield ModalAction("Cancel", "cancel-refresh-session")

    def on_modal_action_pressed(self, event: ModalAction.Pressed) -> None:
        self.dismiss(event.action.action_id == "confirm-refresh-session")

    def action_cancel(self) -> None:
        self.dismiss(False)



