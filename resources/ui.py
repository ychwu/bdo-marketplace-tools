import asyncio
import json
import os
import random
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from rich import box
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from market.api_handler import MarketplaceAPIError
from market.pricing import apply_price_rules, purchase_record_count, purchase_record_spend
from resources.credentials import (
    CredentialStoreError,
    clear_credentials,
    load_credentials,
    save_credentials,
)


APP_TITLE = "Marketplace Tools"
APP_VERSION = "BETA"
APP_VERSION_STYLE = "bold orange3"
BANNER_STYLE = "rgb(255,142,54)"
LOCAL_DATA_PATH = Path(__file__).with_name("local_data.json")
DEFAULT_LOCAL_DATA = {
    "last_check_at": None,
    "last_result": "No checks yet",
    "successful_purchases": 0,
    "silver_spent": 0,
}


def _load_local_data():
    try:
        with LOCAL_DATA_PATH.open("r", encoding="utf-8") as data_file:
            data = json.load(data_file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return DEFAULT_LOCAL_DATA.copy()

    return {
        "last_check_at": data.get("last_check_at"),
        "last_result": data.get("last_result") or DEFAULT_LOCAL_DATA["last_result"],
        "successful_purchases": _safe_int(data.get("successful_purchases")),
        "silver_spent": _safe_int(data.get("silver_spent")),
    }


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _save_local_data(data):
    payload = DEFAULT_LOCAL_DATA.copy()
    payload.update(data)
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    LOCAL_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCAL_DATA_PATH.open("w", encoding="utf-8") as data_file:
        json.dump(payload, data_file, indent=2)
        data_file.write("\n")


def _mask_email(email):
    if not email or "@" not in email:
        return "Not set"

    name, domain = email.split("@", 1)
    if len(name) <= 2:
        masked_name = name[0] + "*"
    else:
        masked_name = name[:2] + "*" * max(2, len(name) - 2)
    return f"{masked_name}@{domain}"


def _format_silver(value):
    if value is None:
        return "No cap"
    return f"{value:,} silver"


def _format_compact_number(value):
    value = int(value or 0)
    sign = "-" if value < 0 else ""
    value = abs(value)
    for suffix, size in (("T", 1_000_000_000_000), ("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if value >= size:
            formatted = f"{value / size:.1f}".rstrip("0").rstrip(".")
            return f"{sign}{formatted}{suffix}"
    return f"{sign}{value}"


def _format_compact_silver(value):
    if value is None:
        return "No cap"
    return f"{_format_compact_number(value)} silver"


def _format_percent(numerator, denominator):
    if denominator <= 0:
        return "0%"
    return f"{(numerator / denominator) * 100:.0f}%"


def _format_duration(seconds):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def _clear_terminal(console):
    console.clear()
    try:
        console.file.write("\033[3J\033[2J\033[H")
        console.file.flush()
    except Exception:
        pass


def _input_hint(prompt, choices=None, default=None):
    parts = [prompt]
    if choices:
        parts.append(f"({', '.join(_choice_label(choice) for choice in choices)})")
    if default not in (None, ""):
        parts.append(f"[default: {default}]")
    return " ".join(parts)


def _choice_label(choice):
    return "Enter" if choice == "" else str(choice)


def _choices_message(choices):
    return ", ".join(_choice_label(choice) for choice in choices)


def _clear_prompt_area(console, line_count):
    console.file.write(f"\033[{line_count}F")
    for _ in range(line_count):
        console.file.write("\033[2K\033[1E")
    console.file.write(f"\033[{line_count}F")
    console.file.flush()


def _status_style(message):
    if not message:
        return "cyan"

    lower_message = message.lower()
    if any(word in lower_message for word in ("cannot", "unable", "failed", "invalid", "required")):
        return "red"
    if any(word in lower_message for word in ("before", "enter a valid", "one of")):
        return "yellow"
    if any(word in lower_message for word in ("set", "updated", "started", "stopped", "complete", "cleared")):
        return "green"
    return "cyan"


def _read_key(timeout=0.1):
    if os.name == "nt":
        import msvcrt

        end_at = time.monotonic() + timeout
        while time.monotonic() < end_at:
            if msvcrt.kbhit():
                char = msvcrt.getwch()
                if char in ("\x00", "\xe0"):
                    msvcrt.getwch()
                    return None
                return char
            time.sleep(0.02)
        return None

    import select
    import termios
    import tty

    file_descriptor = 0
    original_settings = termios.tcgetattr(file_descriptor)
    try:
        tty.setraw(file_descriptor)
        readable, _, _ = select.select([file_descriptor], [], [], timeout)
        if readable:
            char = os.read(file_descriptor, 1).decode(errors="ignore")
            return char
        return None
    finally:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, original_settings)


def _prompt_field(console, prompt, choices=None, default=None, password=False, status=None, status_provider=None):
    hint = _input_hint(prompt, choices=choices, default=default)
    status_message = status
    status_style = _status_style(status_message)
    value = ""
    line_count = 0

    def current_status():
        provided_status = status_provider() if status_provider else None
        if status_message and provided_status:
            return f"{status_message} | {provided_status}"
        if status_message:
            return status_message
        if provided_status:
            return provided_status
        return None

    def render():
        nonlocal line_count
        if line_count:
            _clear_prompt_area(console, line_count)

        width = max(console.size.width - 1, 32)
        border = "─" * width
        active_status = current_status()
        line_count = 4
        if active_status:
            console.print(Text(active_status, style=status_style), overflow="ellipsis", no_wrap=True)
            line_count += 1
        console.print(Text(hint, style="dim"), overflow="ellipsis", no_wrap=True)
        console.print(Text(border, style="bright_black"), overflow="crop", no_wrap=True)
        display_value = "*" * len(value) if password else value
        console.print(Text("⟩ ", style="bold cyan"), end="")
        console.print(Text(display_value), end="")
        console.print()
        console.print(Text(border, style="bright_black"), overflow="crop", no_wrap=True)
        console.file.flush()

    render()
    last_refresh = time.monotonic()

    while True:
        char = _read_key(timeout=0.1)
        if status_provider and time.monotonic() - last_refresh >= 1:
            render()
            last_refresh = time.monotonic()

        if char is None:
            continue
        if char == "\x03":
            raise KeyboardInterrupt
        if char in ("\r", "\n"):
            submitted = value.strip()
            if not submitted and default is not None:
                submitted = str(default)
            if choices and submitted not in choices and submitted.lower() in choices:
                submitted = submitted.lower()
            if choices is None or submitted in choices:
                _clear_prompt_area(console, line_count)
                return submitted

            status_message = f"Enter one of: {_choices_message(choices)}"
            status_style = "red"
            value = ""
            render()
            last_refresh = time.monotonic()
            continue
        if char in ("\b", "\x7f"):
            value = value[:-1]
            render()
            last_refresh = time.monotonic()
            continue
        if char >= " ":
            value += char
            render()
            last_refresh = time.monotonic()


async def _ask_field(console, prompt, choices=None, default=None, password=False, status=None, status_provider=None):
    return await asyncio.to_thread(
        _prompt_field,
        console,
        prompt,
        choices,
        default,
        password,
        status,
        status_provider,
    )


async def _confirm_field(console, prompt, default=False):
    default_choice = "y" if default else "n"
    value = await _ask_field(
        console,
        f"{prompt} y/n",
        choices=["y", "n"],
        default=default_choice,
    )
    return value == "y"


class mainMenu():
    def __init__(self, task_manager, api_handler):
        self.console = Console()
        self.task_manager = task_manager
        self.api_handler = api_handler
        self.loginMenu = loginMenu(api_handler, task_manager, self.console)
        self.input_status = None
        self.main_art = self._build_banner()
        self.main_menu = {
            "1": "Credentials",
            "2": "Login / Refresh Session",
            "3": "Start Monitor",
            "4": "Stop Monitor",
            "5": "Settings",
            "6": "Marketplace Wallet",
            "7": "Stats",
            "8": "Exit",
        }
        self.choices = {
            "1": self.loginMenu.run,
            "2": self.login,
            "3": self.start_monitor,
            "4": self.task_manager.stop_checker,
            "5": self.settings_menu,
            "6": self.mp_inventory,
            "7": self.stats_menu,
            "8": self.exit,
        }

    def _build_banner(self):
        wordmark_lines = [
            "██████╗ ██████╗  ██████╗",
            "██╔══██╗██╔══██╗██╔═══██╗",
            "██████╔╝██║  ██║██║   ██║",
            "██╔══██╗██║  ██║██║   ██║",
            "██████╔╝██████╔╝╚██████╔╝",
            "╚═════╝ ╚═════╝  ╚═════╝",
            "███╗   ███╗ █████╗ ██████╗ ██╗  ██╗███████╗████████╗",
            "████╗ ████║██╔══██╗██╔══██╗██║ ██╔╝██╔════╝╚══██╔══╝",
            "██╔████╔██║███████║██████╔╝█████╔╝ █████╗     ██║",
            "██║╚██╔╝██║██╔══██║██╔══██╗██╔═██╗ ██╔══╝     ██║",
            "██║ ╚═╝ ██║██║  ██║██║  ██║██║  ██╗███████╗   ██║",
            "╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝   ╚═╝",
        ]
        mascot_lines = [
            "                 ███████████",
            "             █████████████████",
            "           ███████     ███████",
            "          ██████   █   ███████",
            "         █████████   █████████",
            "         █████████████████████",
            "        ████  █████████  ████",
            "        █████████████████████",
            "         ███████   █████████",
            "         ███████████████████",
            "          ████████████████",
            "             ███████████",
        ]
        wordmark_width = max(len(line) for line in wordmark_lines)
        return "\n".join(
            f"{wordmark.ljust(wordmark_width)}        {mascot}"
            for wordmark, mascot in zip(wordmark_lines, mascot_lines)
        )

    async def _ask(self, prompt, choices=None, default=None):
        status = self.input_status
        self.input_status = None
        return await _ask_field(
            self.console,
            prompt,
            choices=choices,
            default=default,
            status=status,
            status_provider=self._runtime_status,
        )

    def _runtime_status(self):
        if not self.task_manager.checker_enabled:
            return None
        return f"Runtime {self.task_manager.runtime_label()}"

    async def _confirm(self, prompt, default=False):
        return await _confirm_field(self.console, prompt, default=default)

    async def _pause(self):
        await _ask_field(self.console, "Press Enter to continue", default="")

    def _load_credentials_status(self):
        try:
            email, password = load_credentials()
        except CredentialStoreError as exc:
            self.api_handler.email = None
            self.api_handler.password = None
            return "Credential Store Error", str(exc), "red"

        self.api_handler.email = email
        self.api_handler.password = password

        if email and password:
            return "Ready", _mask_email(email), "green"
        if email:
            return "Password Needed", _mask_email(email), "yellow"
        return "Not Set", "No account configured", "red"

    def _dashboard_panel(self):
        credential_state, credential_detail, credential_style = self._load_credentials_status()
        table = Table(box=box.SIMPLE_HEAVY, expand=True, show_lines=False)
        table.add_column("Area", style="bold", no_wrap=True)
        table.add_column("", justify="center", style="dim", width=3)
        table.add_column("Status", no_wrap=True)
        table.add_column("Details", style="dim")

        login_status = "Logged in" if self.api_handler.login_status else "Not logged in"
        monitor_status = "Running" if self.task_manager.checker_enabled else "Stopped"
        mode = "Buy mode" if self.task_manager.purchase_submission_enabled else "Watch only"
        spend_detail = f"Cap: {_format_compact_silver(self.task_manager.max_spend)} per cycle"
        purchase_rate = _format_percent(
            self.task_manager.session_successful_purchases,
            self.task_manager.session_detected_outfits,
        )
        purchase_detail = (
            f"{self.task_manager.session_successful_purchases}/"
            f"{self.task_manager.session_detected_outfits} bought this session"
        )

        rows = [
            ("Credentials", credential_state, credential_detail, credential_style),
            ("Session", login_status, "Marketplace authentication", "green" if self.api_handler.login_status else "red"),
            ("Monitor", monitor_status, mode, "green" if self.task_manager.checker_enabled else "red"),
            ("Polling", self.task_manager.current_delay_label(), self.task_manager.current_delay_range(), "cyan"),
            ("Purchase Success Rate", purchase_rate, purchase_detail, "cyan"),
            ("Silver Spent", _format_compact_silver(self.task_manager.session_silver_spent), spend_detail, "cyan"),
            ("Runtime", self.task_manager.runtime_label(), "Active monitor session", "cyan"),
        ]

        for area, status, detail, style in rows:
            table.add_row(area, "->", Text(str(status), style=f"bold {style}"), detail)

        return Panel(table, title="Status Dashboard", border_style="orange3", box=box.ROUNDED)

    def _event_log_panel(self):
        if self.task_manager.events:
            log_text = "\n".join(self.task_manager.events)
        else:
            log_text = "No events yet."
        return Panel(log_text, title="Event Log", border_style="bright_black", box=box.ROUNDED)

    def _menu_panel(self):
        table = Table(show_header=False, box=None, expand=True)
        table.add_column("Key", style="bold orange3", width=4)
        table.add_column("Action")
        for key, value in self.main_menu.items():
            table.add_row(key, value)
        return Panel(table, title="Menu", border_style="cyan", box=box.ROUNDED)

    def _title_text(self):
        title = Text()
        title.append(APP_TITLE, style="bold")
        title.append(" ")
        title.append(APP_VERSION, style=APP_VERSION_STYLE)
        return title

    async def display_menu(self):
        _clear_terminal(self.console)
        self._render_menu()

    def _render_menu(self):
        self.console.print(Text(self.main_art, style=BANNER_STYLE))
        self.console.print(self._title_text())
        self.console.print()
        self.console.print(self._dashboard_panel())
        self.console.print(self._event_log_panel())
        self.console.print(self._menu_panel())

    async def run(self):
        while True:
            await self.display_menu()
            choice = await self._ask("Select an action", choices=list(self.main_menu.keys()))
            action = self.choices.get(choice)
            if action:
                _clear_terminal(self.console)
                await action()
                if choice == "4":
                    self.input_status = "Monitor stopped."

    async def login(self):
        self.console.print(
            Panel(
                "Checking the saved marketplace session and refreshing login state.",
                title="Login / Refresh Session",
                border_style="cyan",
                box=box.ROUNDED,
            )
        )
        with self.console.status("Working...", spinner="dots"):
            await self.task_manager.login()
        self.input_status = "Login check complete."

    async def start_monitor(self):
        _clear_terminal(self.console)
        if self.task_manager.purchase_submission_enabled and not self.api_handler.login_status:
            self.task_manager.add_event("Login required before starting the monitor.", "warning")
            self.console.print(
                Panel(
                    "Login or refresh the marketplace session before starting buy mode. Watch-only mode can run without login.",
                    title="Session Required",
                    border_style="yellow",
                    box=box.ROUNDED,
                )
            )
            await self._pause()
            return

        if self.task_manager.purchase_submission_enabled:
            _clear_terminal(self.console)
            self.console.print(self._buy_mode_confirmation_panel())
            confirmed = await self._confirm("Start buy mode with these settings?", default=False)
            if not confirmed:
                return

        await self.task_manager.start_checker()
        if self.task_manager.purchase_submission_enabled:
            self.input_status = "Monitor started in buy mode."
        else:
            self.input_status = "Monitor started in watch-only mode."

    def _buy_mode_confirmation_panel(self):
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold")
        table.add_column()
        table.add_row("Account", _mask_email(self.api_handler.email))
        table.add_row("Mode", "Buy mode")
        table.add_row("Polling interval", f"{self.task_manager.current_delay_label()} ({self.task_manager.current_delay_range()})")
        table.add_row("Spend cap", _format_compact_silver(self.task_manager.max_spend))
        return Panel(table, title="Confirm Buy Mode", border_style="yellow", box=box.ROUNDED)

    async def settings_menu(self):
        while True:
            _clear_terminal(self.console)
            self.console.print(self._settings_panel())
            table = Table(show_header=False, box=None)
            table.add_column("Key", style="bold orange3", width=6)
            table.add_column("Action")
            table.add_row("1", "Set polling interval")
            table.add_row("2", "Toggle watch-only / buy mode")
            table.add_row("3", "Set spend cap")
            table.add_row("Enter", "Back")
            self.console.print(Panel(table, title="Settings", border_style="cyan", box=box.ROUNDED))
            choice = await self._ask("Select a setting", choices=["1", "2", "3", ""])

            if choice == "1":
                await self.task_manager.set_delay(self.console)
                self.input_status = "Polling interval updated."
            elif choice == "2":
                self.task_manager.purchase_submission_enabled = not self.task_manager.purchase_submission_enabled
                mode = "Buy mode" if self.task_manager.purchase_submission_enabled else "Watch only"
                self.input_status = f"Mode changed to {mode}."
            elif choice == "3":
                await self._set_spend_cap()
            elif choice == "":
                return

    def _settings_panel(self):
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold")
        table.add_column()
        mode = "Buy mode" if self.task_manager.purchase_submission_enabled else "Watch only"
        table.add_row("Mode", mode)
        table.add_row("Polling interval", f"{self.task_manager.current_delay_label()} ({self.task_manager.current_delay_range()})")
        table.add_row("Spend cap", _format_compact_silver(self.task_manager.max_spend))
        table.add_row("Tracked categories", "Outfits: male and female marketplace categories")
        return Panel(table, title="Current Configuration", border_style="orange3", box=box.ROUNDED)

    async def _set_spend_cap(self):
        _clear_terminal(self.console)
        self.console.print(
            Panel(
                f"Current cap: {_format_compact_silver(self.task_manager.max_spend)}",
                title="Spend Cap",
                border_style="cyan",
                box=box.ROUNDED,
            )
        )
        value = await self._ask("Max spend per monitor cycle in silver (0 for no cap)", default="0")
        try:
            parsed = int(value)
            if parsed < 0:
                raise ValueError
        except ValueError:
            self.console.print("[red]Enter 0 or a positive integer.[/red]")
            await self._pause()
            return

        self.task_manager.max_spend = parsed or None
        self.input_status = f"Spend cap set to {_format_compact_silver(self.task_manager.max_spend)}."

    async def mp_inventory(self):
        _clear_terminal(self.console)
        try:
            with self.console.status("Loading marketplace wallet...", spinner="dots"):
                response = await self.api_handler.get_mp_inventory()
        except Exception as exc:
            self.task_manager.add_event(f"Wallet lookup failed: {exc}", "error")
            self.console.print(
                Panel(
                    str(exc),
                    title="Marketplace Wallet Error",
                    border_style="red",
                    box=box.ROUNDED,
                )
            )
            await self._pause()
            return

        self.console.print(Panel(JSON.from_data(response), title="Marketplace Wallet", border_style="cyan"))
        await self._pause()

    async def stats_menu(self):
        _clear_terminal(self.console)
        self.task_manager.reload_lifetime_stats()
        table = Table(box=box.SIMPLE_HEAVY, expand=True, show_lines=False)
        table.add_column("Metric", style="bold", no_wrap=True)
        table.add_column("", justify="center", style="dim", width=3)
        table.add_column("Value")
        table.add_row("Lifetime Purchases", "->", str(self.task_manager.lifetime_successful_purchases))
        table.add_row("Lifetime Silver Spent", "->", _format_compact_silver(self.task_manager.lifetime_silver_spent))
        table.add_row("Local Data File", "->", str(LOCAL_DATA_PATH))
        self.console.print(Panel(table, title="Stats", border_style="cyan", box=box.ROUNDED))
        await self._pause()

    async def exit(self):
        await self.task_manager.stop_checker()
        await self.task_manager.stop_login_status_checker()
        self.api_handler.save_session()
        raise SystemExit(0)


class loginMenu():
    def __init__(self, api_handler, task_manager, console):
        self.api_handler = api_handler
        self.task_manager = task_manager
        self.console = console
        self.input_status = None
        self.login_menu = {
            "1": "Set email",
            "2": "Update password",
            "3": "Clear saved credentials",
            "": "Back",
        }
        self.choices = {
            "1": self.get_email,
            "2": self.get_password,
            "3": self.clear_saved_credentials,
            "": self.back_to_main,
        }

    async def _ask(self, prompt, choices=None, default=None):
        status = self.input_status
        self.input_status = None
        return await _ask_field(self.console, prompt, choices=choices, default=default, status=status)

    async def _confirm(self, prompt, default=False):
        return await _confirm_field(self.console, prompt, default=default)

    def _credential_panel(self):
        try:
            email, password = load_credentials()
        except CredentialStoreError as exc:
            email = None
            password = None
            detail = str(exc)
            style = "red"
        else:
            detail = "Ready" if email and password else "Password needed" if email else "Not configured"
            style = "green" if email and password else "yellow" if email else "red"

        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold")
        table.add_column()
        table.add_row("Email", _mask_email(email))
        table.add_row("Password", "Stored in OS keyring" if password else "Not set")
        table.add_row("Status", f"[{style}]{detail}[/{style}]")
        return Panel(table, title="Credentials", border_style="orange3", box=box.ROUNDED)

    async def display_menu(self):
        _clear_terminal(self.console)
        self.console.print(self._credential_panel())
        table = Table(show_header=False, box=None)
        table.add_column("Key", style="bold orange3", width=6)
        table.add_column("Action")
        for key, value in self.login_menu.items():
            table.add_row(_choice_label(key), value)
        self.console.print(Panel(table, title="Credential Menu", border_style="cyan", box=box.ROUNDED))

    async def run(self):
        while True:
            await self.display_menu()
            choice = await self._ask("Select an action", choices=list(self.login_menu.keys()))
            action = self.choices.get(choice)
            if action and await action() == "back":
                break

    async def back_to_main(self):
        return "back"

    async def get_email(self):
        email = await self._ask("Enter account email")
        if not email:
            self.input_status = "Email field cannot be empty."
            return
        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            self.input_status = "Enter a valid email address."
            return

        self.api_handler.email = email
        try:
            save_credentials(email)
        except CredentialStoreError as exc:
            self.task_manager.add_event(f"Unable to save email: {exc}", "error")
            self.input_status = "Unable to save email."
        else:
            self.input_status = "Email has been set."

    async def get_password(self):
        if not self.api_handler.email:
            try:
                email, _ = load_credentials()
            except CredentialStoreError:
                email = None
            self.api_handler.email = email

        if not self.api_handler.email:
            self.input_status = "Set an email before updating the password."
            return

        password = await _ask_field(self.console, "Enter account password", password=True)
        if not password:
            self.input_status = "Password field cannot be empty."
            return

        self.api_handler.password = password
        try:
            save_credentials(self.api_handler.email, password)
        except CredentialStoreError as exc:
            self.task_manager.add_event(f"Unable to save password: {exc}", "error")
            self.input_status = "Unable to save password."
        else:
            self.input_status = "Password has been set."

    async def clear_saved_credentials(self):
        confirmed = await self._confirm("Clear saved email and keyring password?", default=False)
        if not confirmed:
            return

        try:
            clear_credentials()
        except CredentialStoreError as exc:
            self.task_manager.add_event(f"Unable to clear credentials: {exc}", "error")
            self.input_status = "Unable to clear saved credentials."
            return

        self.api_handler.email = None
        self.api_handler.password = None
        self.input_status = "Saved credentials cleared."


class backgroundTasks():
    def __init__(self, api_handler):
        local_data = _load_local_data()
        self.api_handler = api_handler
        self.checker_task = None
        self.login_checker_task = None
        self.checker_enabled = False
        self.delay_choices = {
            "1": ("Fast", (3, 5)),
            "2": ("Balanced", (5, 10)),
            "3": ("Conservative", (15, 30)),
        }
        self.delay = "3"
        self.events = deque(maxlen=9)
        self.lifetime_last_check_at = local_data["last_check_at"]
        self.lifetime_last_result = local_data["last_result"]
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
        self.lifetime_last_check_at = local_data["last_check_at"]
        self.lifetime_last_result = local_data["last_result"]
        self.lifetime_successful_purchases = local_data["successful_purchases"]
        self.lifetime_silver_spent = local_data["silver_spent"]

    def save_local_data(self):
        _save_local_data(
            {
                "last_check_at": self.lifetime_last_check_at,
                "last_result": self.lifetime_last_result,
                "successful_purchases": self.lifetime_successful_purchases,
                "silver_spent": self.lifetime_silver_spent,
            }
        )

    def add_event(self, message, level="info"):
        styles = {
            "info": "cyan",
            "success": "green",
            "warning": "yellow",
            "error": "red",
        }
        timestamp = datetime.now().strftime("%H:%M:%S")
        style = styles.get(level, "cyan")
        self.events.append(f"[dim]{timestamp}[/dim] [{style}]{message}[/{style}]")

    def current_delay_label(self):
        return self.delay_choices[self.delay][0]

    def current_delay_range(self):
        low, high = self.delay_choices[self.delay][1]
        return f"{low}-{high}s"

    def runtime_label(self):
        if not self.checker_enabled or self.checker_started_at is None:
            return "00:00:00"
        return _format_duration(time.monotonic() - self.checker_started_at)

    async def start_checker(self):
        if self.purchase_submission_enabled and not self.api_handler.login_status:
            return

        if self.checker_task is None or self.checker_task.done():
            self.checker_started_at = time.monotonic()
            self.checker_task = asyncio.create_task(self.checker())
            self.checker_enabled = True

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

    async def checker_status(self):
        return "Running" if self.checker_enabled else "Stopped"

    async def checker(self):
        try:
            while True:
                try:
                    buyList = await self.api_handler.check_stock()
                except Exception as exc:
                    self.add_event(f"Marketplace check failed: {exc}", "error")
                else:
                    if buyList:
                        detected_count = sum(int(item[1]) for item in buyList)
                        self.session_detected_outfits += detected_count
                        if self.purchase_submission_enabled:
                            self.add_event(f"Outfit detected: {detected_count} available outfits. Attempting purchase.", "success")
                            await self.buy_item(buyList)
                        else:
                            self.add_event(f"Outfit detected: {detected_count} available outfits.", "success")

                sleep_duration = random.uniform(*self.delay_choices[self.delay][1])
                await asyncio.sleep(sleep_duration)
        except asyncio.CancelledError:
            raise

    async def check_login_status(self):
        return "Logged in" if self.api_handler.login_status else "Not logged in"

    async def check_credentials(self):
        if self.api_handler.email and self.api_handler.password:
            return "Set"
        return "Not set"

    async def buy_item(self, buyList):
        updated_buyList = await self.price_calc(buyList)
        capped_buyList = self._apply_spend_cap(updated_buyList)

        if not capped_buyList:
            self.add_event("Purchase skipped: spend cap would be exceeded.", "warning")
            return

        try:
            summary = await self.api_handler.buy_item(capped_buyList)
        except MarketplaceAPIError as exc:
            self.add_event(f"Purchase request failed: {exc}", "error")
            return

        purchase_records = summary.get("purchase_records", [])
        purchased_count = purchase_record_count(purchase_records)
        silver_spent = purchase_record_spend(purchase_records)
        self.session_successful_purchases += purchased_count
        self.session_silver_spent += silver_spent
        self.lifetime_successful_purchases += purchased_count
        self.lifetime_silver_spent += silver_spent
        self.save_local_data()

        for event in summary["events"]:
            if isinstance(event, dict):
                self.add_event(event.get("message", ""), event.get("level", "info"))
            else:
                self.add_event(event, "success" if "succeeded" in event else "warning")

        if purchased_count == 0:
            self.add_event("Purchase attempt completed without a successful request.", "warning")

    def _apply_spend_cap(self, buyList):
        if self.max_spend is None:
            return buyList

        capped = []
        remaining = self.max_spend

        for item_id, stock, price in buyList:
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

    async def price_calc(self, buyList):
        modified_list, fallback_items = apply_price_rules(buyList)
        if fallback_items:
            self.add_event(f"Fallback pricing applied to {len(fallback_items)} outfit listings.", "warning")
        return modified_list

    async def login(self):
        try:
            status = await self.api_handler.is_session_expired()
        except MarketplaceAPIError as exc:
            self.api_handler.login_status = False
            self.add_event(f"Session check failed: {exc}", "error")
            status = -1

        if status == 0:
            self.api_handler.login_status = True
            self.add_event("Existing marketplace session is valid.", "success")
            self.start_login_status_checker()
            return

        if not self.api_handler.email or not self.api_handler.password:
            self.add_event("Please configure credentials before logging in.", "warning")
            return

        try:
            status = await self.api_handler.login()
        except MarketplaceAPIError as exc:
            self.api_handler.login_status = False
            self.add_event(f"Login failed: {exc}", "error")
            return

        if status == 1:
            self.api_handler.login_status = True
            self.api_handler.save_session()
            self.add_event("Login successful; session saved.", "success")
            self.start_login_status_checker()
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
                    self.add_event("Session expired. Attempting re-authentication.", "warning")
                    try:
                        login_status = await self.api_handler.login()
                    except MarketplaceAPIError as exc:
                        self.add_event(f"Re-authentication failed: {exc}", "error")
                        break

                    if login_status == 1:
                        self.api_handler.login_status = True
                        self.api_handler.save_session()
                        self.add_event("Re-authentication successful.", "success")
                    else:
                        self.add_event("Re-authentication failed.", "error")
                        break
                else:
                    self.api_handler.login_status = True
                    self.add_event("Session still valid.")
        except asyncio.CancelledError:
            raise

    async def set_delay(self, console=None):
        console = console or Console()
        _clear_terminal(console)
        table = Table(show_header=False, box=None)
        table.add_column("Key", style="bold orange3", width=4)
        table.add_column("Preset")
        table.add_column("Range")
        for key, value in self.delay_choices.items():
            low, high = value[1]
            table.add_row(key, value[0], f"{low}-{high}s")

        console.print(Panel(table, title="Polling Interval", border_style="cyan", box=box.ROUNDED))
        choice = await _ask_field(console, "Select interval", choices=list(self.delay_choices.keys()))
        self.delay = choice
