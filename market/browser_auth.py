import asyncio
import inspect
from pathlib import Path
from urllib.parse import urlparse

from market.api_handler import GAME_TRADE_URL, TRADE_URL


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STEAM_MARKET_PROFILE_PATH = PROJECT_ROOT / "resources" / "browser_profiles" / "steam-market"
STEAM_MARKET_DIAGNOSTIC_PROFILE_PATH = PROJECT_ROOT / "resources" / "browser_profiles" / "steam-market-diagnostic"
AUTH_START_URL = f"{TRADE_URL}/"
STEAM_PROFILE_PREP_START_URL = "https://www.naeu.playblackdesert.com/en-US"
MARKET_COOKIE_URLS = (
    f"{TRADE_URL}/",
    f"{GAME_TRADE_URL}/",
)
MARKET_COOKIE_HOSTS = tuple(urlparse(url).hostname for url in MARKET_COOKIE_URLS)
OTP_ROUTE_MARKERS = (
    "/en-us/Member/Login/CheckOtp",
    "/en-us/Member/Login/LoginOtpAuth",
    "/en-us/Member/Signin/Otp",
    "/en-us/Member/SignIn/OTPAuthenticate",
)
OAUTH_CALLBACK_PATH = "/Pearlabyss/Oauth2CallBack"
LIKELY_MARKET_AUTH_COOKIE_NAMES = {
    "TradeAuth_Session",
    "__RequestVerificationToken",
}
DEFAULT_BROWSER_AUTH_TIMEOUT_SECONDS = 900
STEAM_BROWSER_CHANNEL = "chrome"
COOKIEBOT_REQUIRED_CONSENT_SELECTORS = (
    "#CybotCookiebotDialogBodyButtonDecline",
    "button:has-text('Only Accept Required')",
    "button:has-text('Accept Necessary')",
    "button:has-text('Accept Required')",
)
COOKIEBOT_DIALOG_SELECTOR = "#CybotCookiebotDialog"
COOKIE_CONSENT_SAVED = "saved"
COOKIE_CONSENT_MANUAL = "manual"
COOKIE_CONSENT_NOT_FOUND = "not_found"
PA_STEAM_LOGIN_SELECTORS = (
    "#btnSteam",
    "button[data-type='steam']",
    "button:has-text('Log in with Steam')",
)
STEAM_CONFIRM_LOGIN_SELECTORS = (
    "#imageLogin",
    "input[type='submit'][value='Sign In']",
    "input.btn_green_white_innerfade",
)
STEAM_AUTO_LOGIN_CLICK_TIMEOUT_MS = 1000
STEAM_AUTO_LOGIN_MISSING_NOTICE_SECONDS = 5
BROWSER_AUTH_POLL_SECONDS = 0.25
STEAM_AUTO_LOGIN_DISABLED = "disabled"
STEAM_AUTO_LOGIN_CLICKED = "clicked"
STEAM_AUTO_LOGIN_WAITING = "waiting"
STEAM_AUTO_LOGIN_MANUAL_NEEDED = "manual_needed"
STEAM_AUTO_LOGIN_SKIPPED = "skipped"


class BrowserAuthError(RuntimeError):
    pass


class BrowserAuthUnavailable(BrowserAuthError):
    pass


async def acquire_steam_market_cookies(
    status_callback=None,
    *,
    timeout_seconds=DEFAULT_BROWSER_AUTH_TIMEOUT_SECONDS,
    profile_path=STEAM_MARKET_PROFILE_PATH,
    start_url=AUTH_START_URL,
    auto_steam_login=False,
):
    try:
        from patchright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - depends on optional runtime
        raise BrowserAuthUnavailable(
            "Patchright is not installed. Install requirements, then run `patchright install chromium`."
        ) from exc

    profile_path = Path(profile_path)
    profile_path.mkdir(parents=True, exist_ok=True)
    opening_message = "Opening Steam Account browser session in Chrome. Complete Steam/PA login in the browser."
    if auto_steam_login:
        opening_message = (
            "Opening Steam Account browser session in Chrome. Automatic Steam re-auth will continue when possible."
        )
    await _emit_status(status_callback, opening_message, "info")

    context = None
    try:
        async with async_playwright() as playwright:
            context = await _launch_persistent_chrome_context(playwright, profile_path)
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                await page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                await _emit_status(status_callback, "Waiting for Steam/PA login in the browser.", "info")

            return await _wait_for_market_cookies(
                context,
                status_callback,
                timeout_seconds,
                auto_steam_login=auto_steam_login,
            )
    except BrowserAuthError:
        raise
    except Exception as exc:
        raise BrowserAuthError(_browser_launch_error_message(exc)) from exc
    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass


async def prepare_steam_browser_profile(
    status_callback=None,
    *,
    profile_path=STEAM_MARKET_PROFILE_PATH,
    start_url=STEAM_PROFILE_PREP_START_URL,
):
    try:
        from patchright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - depends on optional runtime
        raise BrowserAuthUnavailable(
            "Patchright is not installed. Install requirements before opening the Steam setup browser."
        ) from exc

    profile_path = Path(profile_path)
    profile_path.mkdir(parents=True, exist_ok=True)
    await _emit_status(
        status_callback,
        "Opening initial Steam browser setup in Chrome. Let the Black Desert site load, then close Chrome.",
        "info",
    )

    context = None
    try:
        async with async_playwright() as playwright:
            context = await _launch_persistent_chrome_context(playwright, profile_path)
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                await page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
                consent_result = await _accept_required_cookie_consent_if_available(page, status_callback)
            except Exception:
                await _emit_status(status_callback, "Steam setup browser is open. Continue setup manually.", "warning")
                consent_result = COOKIE_CONSENT_MANUAL

            if consent_result == COOKIE_CONSENT_MANUAL:
                await _wait_for_all_pages_closed(context)
    except Exception as exc:
        raise BrowserAuthError(_browser_launch_error_message(exc)) from exc
    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass


async def open_blank_steam_browser_diagnostic(
    status_callback=None,
    *,
    profile_path=STEAM_MARKET_DIAGNOSTIC_PROFILE_PATH,
):
    try:
        from patchright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - depends on optional runtime
        raise BrowserAuthUnavailable(
            "Patchright is not installed. Install requirements before opening the diagnostic browser."
        ) from exc

    profile_path = Path(profile_path)
    profile_path.mkdir(parents=True, exist_ok=True)
    await _emit_status(
        status_callback,
        "Opening blank Chrome diagnostic browser. Navigate manually and close it when HAR capture is done.",
        "info",
    )

    context = None
    try:
        async with async_playwright() as playwright:
            context = await _launch_persistent_chrome_context(playwright, profile_path)
            if not context.pages:
                await context.new_page()

            await _wait_for_all_pages_closed(context)
    except Exception as exc:
        raise BrowserAuthError(_browser_launch_error_message(exc)) from exc
    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass


async def _wait_for_market_cookies(context, status_callback, timeout_seconds, *, auto_steam_login=False):
    deadline = asyncio.get_running_loop().time() + float(timeout_seconds)
    callback_seen = False
    auth_flow_seen = False
    emitted_states = set()
    auto_login_state = _new_steam_auto_login_state()

    while asyncio.get_running_loop().time() < deadline:
        now = asyncio.get_running_loop().time()
        pages = [page for page in context.pages if not _page_is_closed(page)]
        if not pages:
            raise BrowserAuthError("Browser closed before a marketplace session could be captured.")

        market_active = False
        for page in pages:
            state, is_callback = _classify_url(getattr(page, "url", ""))
            if is_callback:
                callback_seen = True
            if state in {"pa", "steam", "otp"}:
                auth_flow_seen = True
            if state == "market":
                market_active = True
            if state and state not in emitted_states:
                emitted_states.add(state)
                message, level = _status_for_state(state)
                await _emit_status(status_callback, message, level)
            auto_login_result = STEAM_AUTO_LOGIN_SKIPPED
            if _should_attempt_steam_auto_login(state, auth_flow_seen, callback_seen):
                auto_login_result = await _maybe_run_steam_auto_login(
                    page,
                    state,
                    enabled=auto_steam_login,
                    tracking=auto_login_state,
                    status_callback=status_callback,
                    now=now,
                )
            if auto_login_result in {STEAM_AUTO_LOGIN_CLICKED, STEAM_AUTO_LOGIN_MANUAL_NEEDED}:
                auth_flow_seen = True
        cookies = filter_market_cookies(await context.cookies(list(MARKET_COOKIE_URLS)))
        if _market_cookie_capture_ready(cookies, callback_seen, market_active, auth_flow_seen):
            await _emit_status(status_callback, "Marketplace cookies captured. Validating session.", "info")
            return cookies

        await asyncio.sleep(BROWSER_AUTH_POLL_SECONDS)

    raise BrowserAuthError("Steam Account browser session timed out before Central Market cookies were captured.")


async def _launch_persistent_chrome_context(playwright, profile_path):
    return await playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_path),
        channel=STEAM_BROWSER_CHANNEL,
        headless=False,
        viewport={"width": 1280, "height": 900},
    )


async def _wait_for_all_pages_closed(context):
    while any(not _page_is_closed(page) for page in context.pages):
        await asyncio.sleep(1)


async def _accept_required_cookie_consent_if_available(page, status_callback=None):
    for selector in COOKIEBOT_REQUIRED_CONSENT_SELECTORS:
        try:
            await page.locator(selector).first.click(timeout=8000)
        except Exception:
            continue

        if await _cookiebot_dialog_hidden(page):
            await _emit_status(status_callback, "Required cookie consent saved in the Steam browser profile.", "info")
            return COOKIE_CONSENT_SAVED
        else:
            await _emit_status(
                status_callback,
                "Required cookie consent click sent; continue manually if the banner remains.",
                "info",
            )
            return COOKIE_CONSENT_MANUAL
    return COOKIE_CONSENT_NOT_FOUND


def _new_steam_auto_login_state():
    return {
        "clicked": set(),
        "missing_started_at": {},
        "missing_reported": set(),
    }


def _should_attempt_steam_auto_login(state, auth_flow_seen, callback_seen):
    if state == "market" and (auth_flow_seen or callback_seen):
        return False
    return True


async def _maybe_run_steam_auto_login(
    page,
    state,
    *,
    enabled,
    tracking,
    status_callback=None,
    now=None,
    missing_notice_seconds=STEAM_AUTO_LOGIN_MISSING_NOTICE_SECONDS,
):
    if not enabled:
        return STEAM_AUTO_LOGIN_DISABLED

    targets = _steam_auto_login_targets(page, state)
    if not targets:
        return STEAM_AUTO_LOGIN_SKIPPED

    now = asyncio.get_running_loop().time() if now is None else now
    result = STEAM_AUTO_LOGIN_SKIPPED
    for scope, config_state in targets:
        scope_result = await _maybe_run_steam_auto_login_target(
            scope,
            config_state,
            tracking=tracking,
            status_callback=status_callback,
            now=now,
            missing_notice_seconds=missing_notice_seconds,
        )
        if scope_result in {STEAM_AUTO_LOGIN_CLICKED, STEAM_AUTO_LOGIN_MANUAL_NEEDED}:
            return scope_result
        if scope_result == STEAM_AUTO_LOGIN_WAITING:
            result = STEAM_AUTO_LOGIN_WAITING

    return result


async def _maybe_run_steam_auto_login_target(
    scope,
    state,
    *,
    tracking,
    status_callback,
    now,
    missing_notice_seconds,
):
    config = _steam_auto_login_config(state)
    if config is None:
        return STEAM_AUTO_LOGIN_SKIPPED

    selector_key, selectors, clicked_message, missing_message = config
    key = (id(scope), selector_key, getattr(scope, "url", ""))
    if key in tracking["clicked"]:
        return STEAM_AUTO_LOGIN_SKIPPED

    if await _click_first_available_selector(scope, selectors, timeout=STEAM_AUTO_LOGIN_CLICK_TIMEOUT_MS):
        tracking["clicked"].add(key)
        tracking["missing_started_at"].pop(key, None)
        await _emit_status(status_callback, clicked_message, "info")
        return STEAM_AUTO_LOGIN_CLICKED

    started_at = tracking["missing_started_at"].setdefault(key, now)
    if now - started_at >= missing_notice_seconds and key not in tracking["missing_reported"]:
        tracking["missing_reported"].add(key)
        await _emit_status(status_callback, missing_message, "warning")
        return STEAM_AUTO_LOGIN_MANUAL_NEEDED

    return STEAM_AUTO_LOGIN_WAITING


def _steam_auto_login_targets(page, state):
    targets = []
    seen = set()

    def add_target(scope, target_state):
        if target_state not in {"pa", "steam"}:
            return
        key = (id(scope), target_state)
        if key in seen:
            return
        seen.add(key)
        targets.append((scope, target_state))

    add_target(page, _steam_auto_login_target_state(state))
    for frame in getattr(page, "frames", []) or []:
        frame_state, _is_callback = _classify_url(getattr(frame, "url", ""))
        add_target(frame, _steam_auto_login_target_state(frame_state))

    return targets


def _steam_auto_login_target_state(state):
    if state in {"pa", "steam"}:
        return state
    if state is None:
        return "pa"
    return None


def _steam_auto_login_config(state):
    if state == "pa":
        return (
            "pa_steam_login",
            PA_STEAM_LOGIN_SELECTORS,
            "Automatic Steam re-auth clicked Log in with Steam.",
            "Automatic Steam re-auth is waiting for manual input on the Pearl Abyss page.",
        )
    if state == "steam":
        return (
            "steam_confirm_login",
            STEAM_CONFIRM_LOGIN_SELECTORS,
            "Automatic Steam re-auth clicked Steam Sign In.",
            "Automatic Steam re-auth is waiting for manual input on the Steam page.",
        )
    return None


async def _click_first_available_selector(page, selectors, timeout):
    for selector in selectors:
        try:
            await page.locator(selector).first.click(timeout=timeout)
            return True
        except Exception:
            continue
    return False


async def _cookiebot_dialog_hidden(page):
    try:
        await page.locator(COOKIEBOT_DIALOG_SELECTOR).wait_for(state="hidden", timeout=3000)
        return True
    except Exception:
        return False


def filter_market_cookies(cookies):
    filtered = []
    for cookie in cookies or []:
        if not isinstance(cookie, dict):
            continue

        domain = cookie.get("domain") or ""
        if not domain or not _domain_applies_to_market(domain):
            continue

        filtered.append(
            {
                "name": cookie.get("name"),
                "value": cookie.get("value"),
                "domain": domain,
                "path": cookie.get("path") or "/",
                "secure": bool(cookie.get("secure")),
                "expires": cookie.get("expires"),
            }
        )
    return filtered


def _domain_applies_to_market(domain):
    normalized = domain.lstrip(".").lower()
    for host in MARKET_COOKIE_HOSTS:
        if host == normalized or normalized == "naeu.playblackdesert.com":
            return True
    return False


def _has_likely_market_auth_cookie(cookies):
    return any(cookie.get("name") in LIKELY_MARKET_AUTH_COOKIE_NAMES for cookie in cookies)


def _market_cookie_capture_ready(cookies, callback_seen, market_active, auth_flow_seen):
    if not cookies:
        return False
    if callback_seen:
        return True
    if not market_active:
        return False
    return bool(auth_flow_seen or _has_likely_market_auth_cookie(cookies))


def _classify_url(url):
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    lower_path = path.lower()

    if host == "steamcommunity.com":
        return "steam", False

    if host == "account.pearlabyss.com":
        for marker in OTP_ROUTE_MARKERS:
            if lower_path == marker.lower():
                return "otp", False
        return "pa", False

    if host == "na-trade.naeu.playblackdesert.com":
        return "market", lower_path == OAUTH_CALLBACK_PATH.lower()

    return None, False


def _status_for_state(state):
    if state == "steam":
        return "Waiting for Steam confirmation in the browser.", "info"
    if state == "otp":
        return "OTP required. Complete verification in the browser.", "warning"
    if state == "pa":
        return "Waiting for Pearl Abyss authorization in the browser.", "info"
    return "Waiting for Steam/PA login in the browser.", "info"


def _browser_launch_error_message(exc):
    details = _single_line(str(exc))
    lower_details = details.lower()
    missing_browser = (
        "executable doesn't exist" in lower_details
        or "not found" in lower_details
        or "could not find" in lower_details
    )
    if missing_browser and "chrome" in lower_details and "ms-playwright" not in lower_details:
        return "Google Chrome is not available for Patchright. Install Chrome, then refresh the Steam session again."
    if "executable doesn't exist" in lower_details or "playwright was just installed or updated" in lower_details:
        return "Patchright Chromium is not installed. Run `py -m patchright install chromium`, then refresh the Steam session again."
    if not details:
        return "Browser authentication failed before marketplace cookies were captured."
    return f"Browser authentication failed before marketplace cookies were captured: {details}"


def _single_line(message):
    lines = [line.strip() for line in str(message or "").splitlines() if line.strip()]
    return " ".join(lines)


def _page_is_closed(page):
    try:
        return page.is_closed()
    except Exception:
        return True


async def _emit_status(callback, message, level="info"):
    if callback is None:
        return
    result = callback(message, level)
    if inspect.isawaitable(result):
        await result
