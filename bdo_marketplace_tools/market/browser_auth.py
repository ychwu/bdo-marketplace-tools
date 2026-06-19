import asyncio
import inspect
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from bdo_marketplace_tools.market.api_handler import GAME_TRADE_URL, TRADE_URL
from bdo_marketplace_tools.storage.paths import (
    DATA_DIR,
    STEAM_MARKET_DIAGNOSTIC_PROFILE_PATH,
    STEAM_MARKET_PROFILE_PATH,
)


# Off by default. Set BDO_BROWSER_AUTH_TRACE=1 to write a timestamped, value-free trace of the
# browser auth cookie capture to data/auth-trace.log for diagnosing capture timing.
AUTH_TRACE_ENABLED = os.environ.get("BDO_BROWSER_AUTH_TRACE") == "1"


def _auth_trace(message):
    if not AUTH_TRACE_ENABLED:
        return
    try:
        with (DATA_DIR / "auth-trace.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{time.monotonic():.3f} {message}\n")
    except Exception:
        pass


AUTH_START_URL = f"{TRADE_URL}/"
BDO_SITE_BOOTSTRAP_URL = "https://www.naeu.playblackdesert.com/en-US"
STEAM_PROFILE_PREP_START_URL = BDO_SITE_BOOTSTRAP_URL
STEAM_PROFILE_PREP_LOGIN_URL = "https://store.steampowered.com/login"
STEAM_STORE_URL = "https://store.steampowered.com/"
STEAM_COMMUNITY_URL = "https://steamcommunity.com/"
MARKET_COOKIE_URLS = (
    f"{TRADE_URL}/",
    f"{GAME_TRADE_URL}/",
)
MARKET_COOKIE_HOSTS = tuple(urlparse(url).hostname for url in MARKET_COOKIE_URLS)
STEAM_PROFILE_COOKIE_URLS = (
    STEAM_STORE_URL,
    STEAM_COMMUNITY_URL,
)
OTP_ROUTE_MARKERS = (
    "/en-us/Member/Login/CheckOtp",
    "/en-us/Member/Login/LoginOtpAuth",
    "/en-us/Member/Signin/Otp",
    "/en-us/Member/SignIn/OTPAuthenticate",
)
OAUTH_CALLBACK_PATH = "/Pearlabyss/Oauth2CallBack"
MARKET_SESSION_COOKIE_NAMES = {
    "TradeAuth_Session",
}
DEFAULT_BROWSER_AUTH_TIMEOUT_SECONDS = 900
DEFAULT_STEAM_PROFILE_SETUP_TIMEOUT_SECONDS = 900
STEAM_BROWSER_CHANNEL = "chrome"
COOKIEBOT_REQUIRED_CONSENT_SELECTORS = (
    "#CybotCookiebotDialogBodyButtonDecline",
    "button:has-text('Only Accept Required')",
    "button:has-text('Accept Necessary')",
    "button:has-text('Accept Required')",
)
COOKIEBOT_DIALOG_SELECTOR = "#CybotCookiebotDialog"
COOKIEBOT_DIALOG_DETECTION_TIMEOUT_MS = 1500
COOKIEBOT_CONSENT_CLICK_TIMEOUT_MS = 1500
COOKIE_CONSENT_SAVED = "saved"
COOKIE_CONSENT_MANUAL = "manual"
COOKIE_CONSENT_NOT_FOUND = "not_found"
COOKIE_CONSENT_WAITING = "waiting"
COOKIE_CONSENT_SKIPPED = "skipped"
PA_STEAM_LOGIN_SELECTORS = (
    "#btnSteam",
    "button[data-type='steam']",
    "button:has-text('Log in with Steam')",
)
PA_EMAIL_SELECTORS = (
    "#_email",
    "input[name='_email']",
    "input[inputmode='email']",
)
PA_PASSWORD_SELECTORS = (
    "#_password",
    "input[name='_password']",
    "input[type='password']",
)
PA_LOGIN_BUTTON_SELECTORS = (
    "#btnLogin",
    "button.js-btnLastLoginCheck",
    "button[data-type='original']",
    "button:has-text('Log in')",
)
STEAM_CONFIRM_LOGIN_SELECTORS = (
    "#imageLogin",
    "input[type='submit'][value='Sign In']",
    "input.btn_green_white_innerfade",
)
STEAM_AUTO_LOGIN_CLICK_TIMEOUT_MS = 1000
STEAM_AUTO_LOGIN_MISSING_NOTICE_SECONDS = 5
PA_AUTO_LOGIN_FILL_TIMEOUT_MS = 1000
PA_AUTO_LOGIN_CLICK_TIMEOUT_MS = 1000
PA_AUTO_LOGIN_MISSING_NOTICE_SECONDS = 5
PA_CONSENT_BUTTON_READY_TIMEOUT_MS = 250
BROWSER_AUTH_POLL_SECONDS = 0.25
BROWSER_PAGE_CLOSE_TIMEOUT_SECONDS = 0.5
BROWSER_CONTEXT_CLOSE_TIMEOUT_SECONDS = 2
STEAM_PROFILE_SETUP_POLL_SECONDS = 0.5
STEAM_AUTO_LOGIN_DISABLED = "disabled"
STEAM_AUTO_LOGIN_CLICKED = "clicked"
STEAM_AUTO_LOGIN_WAITING = "waiting"
STEAM_AUTO_LOGIN_MANUAL_NEEDED = "manual_needed"
STEAM_AUTO_LOGIN_SKIPPED = "skipped"
PA_AUTO_LOGIN_DISABLED = "disabled"
PA_AUTO_LOGIN_SUBMITTED = "submitted"
PA_AUTO_LOGIN_WAITING = "waiting"
PA_AUTO_LOGIN_MANUAL_NEEDED = "manual_needed"
PA_AUTO_LOGIN_SKIPPED = "skipped"
STEAM_LOGIN_COOKIE_NAMES = {
    "steamLoginSecure",
}
STEAM_LOGGED_IN_SELECTORS = (
    "#account_pulldown",
    ".user_avatar",
)


class BrowserAuthError(RuntimeError):
    pass


class BrowserAuthUnavailable(BrowserAuthError):
    pass


async def acquire_market_cookies(
    status_callback=None,
    *,
    timeout_seconds=DEFAULT_BROWSER_AUTH_TIMEOUT_SECONDS,
    profile_path=STEAM_MARKET_PROFILE_PATH,
    start_url=AUTH_START_URL,
    bootstrap_url=None,
    auto_steam_login=False,
    auto_pa_login=False,
    pa_email=None,
    pa_password=None,
    handle_pa_cookie_consent=False,
    pa_cookie_consent_callback=None,
    account_label="Steam Account",
):
    try:
        from patchright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - depends on optional runtime
        raise BrowserAuthUnavailable(
            "Patchright is not installed. Install requirements, then run `patchright install chromium`."
        ) from exc

    profile_path = Path(profile_path)
    profile_path.mkdir(parents=True, exist_ok=True)
    opening_message = f"Opening {account_label} browser session in Chrome. Complete login in the browser."
    if auto_steam_login:
        opening_message = (
            f"Opening {account_label} browser session in Chrome. Automatic Steam re-auth will continue when possible."
        )
    elif auto_pa_login:
        opening_message = (
            f"Opening {account_label} browser session in Chrome. Saved Pearl Abyss credentials will be submitted when possible."
        )
    await _emit_status(status_callback, opening_message, "info")

    context = None
    try:
        async with async_playwright() as playwright:
            context = await _launch_persistent_chrome_context(playwright, profile_path)
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                if bootstrap_url:
                    await _bootstrap_browser_profile(page, status_callback, bootstrap_url, account_label)
                try:
                    await page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
                except Exception:
                    await _emit_status(status_callback, f"Waiting for {account_label} login in the browser.", "info")
                return await _wait_for_market_cookies(
                    context,
                    status_callback,
                    timeout_seconds,
                    auto_steam_login=auto_steam_login,
                    auto_pa_login=auto_pa_login,
                    pa_email=pa_email,
                    pa_password=pa_password,
                    handle_pa_cookie_consent=handle_pa_cookie_consent,
                    pa_cookie_consent_callback=pa_cookie_consent_callback,
                    account_label=account_label,
                )
            finally:
                await _close_browser_context(context, status_callback)
                context = None
    except BrowserAuthError:
        raise
    except Exception as exc:
        raise BrowserAuthError(_browser_launch_error_message(exc)) from exc
    finally:
        if context is not None:
            await _close_browser_context(context, status_callback)


async def prepare_steam_browser_profile(
    status_callback=None,
    *,
    profile_path=STEAM_MARKET_PROFILE_PATH,
    start_url=STEAM_PROFILE_PREP_START_URL,
    steam_login_url=STEAM_PROFILE_PREP_LOGIN_URL,
    timeout_seconds=DEFAULT_STEAM_PROFILE_SETUP_TIMEOUT_SECONDS,
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
        "Opening initial Steam browser setup in Chrome. The window will close automatically when setup is saved.",
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
                await _wait_for_cookie_consent_manual_completion(page, context)

            await _emit_status(
                status_callback,
                "Opening Steam login. Complete Steam login in the browser; the window will close once detected.",
                "info",
            )
            try:
                await page.goto(steam_login_url, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                await _emit_status(status_callback, "Waiting for Steam login in the browser.", "info")
            await _wait_for_steam_profile_login(context, status_callback, timeout_seconds)
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


async def clear_steam_browser_profile_cookies(
    *,
    profile_path=STEAM_MARKET_PROFILE_PATH,
):
    try:
        from patchright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - depends on optional runtime
        raise BrowserAuthUnavailable(
            "Patchright is not installed. Install requirements before clearing browser cookies."
        ) from exc

    profile_path = Path(profile_path)
    profile_path.mkdir(parents=True, exist_ok=True)

    context = None
    try:
        async with async_playwright() as playwright:
            context = await _launch_persistent_chrome_context(playwright, profile_path)
            if not context.pages:
                await context.new_page()
            cookies = await context.cookies()
            await context.clear_cookies()
            return len(cookies)
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


async def _wait_for_market_cookies(
    context,
    status_callback,
    timeout_seconds,
    *,
    auto_steam_login=False,
    auto_pa_login=False,
    pa_email=None,
    pa_password=None,
    handle_pa_cookie_consent=False,
    pa_cookie_consent_callback=None,
    account_label="Steam Account",
):
    deadline = asyncio.get_running_loop().time() + float(timeout_seconds)
    callback_seen = False
    auth_flow_seen = False
    emitted_states = set()
    auto_login_state = _new_steam_auto_login_state()
    pa_auto_login_state = _new_pa_auto_login_state()
    pa_cookie_consent_state = _new_pa_cookie_consent_state()
    pa_cookie_consent_completed = not handle_pa_cookie_consent
    pa_credentials_submitted = False

    # Snapshot any marketplace session cookie value already in the persistent profile so a
    # fresh login is recognized by a *changed* TradeAuth_Session value, not its mere presence.
    # This is what lets capture close as soon as login completes without waiting for the market
    # page, while never closing on a stale pre-login cookie left over in the profile.
    baseline_session_values = _market_session_cookie_values(
        filter_market_cookies(await context.cookies(list(MARKET_COOKIE_URLS)))
    )

    # The marketplace session cookies (TradeAuth_Session / __RequestVerificationToken) are set on
    # the /Pearlabyss/Oauth2CallBack 302. That redirect never becomes page.url, so polling can't
    # observe it, and context.cookies() may not surface the new cookie until the final market
    # document commits. Reading cookies the instant the callback *response* arrives lets capture
    # close at login success instead of after the market page loads.
    _auth_trace(f"START label={account_label!r} baseline_session_count={len(baseline_session_values)}")
    captured_at_callback = []
    callback_done = asyncio.Event()
    last_trace_sig = None

    async def _read_market_cookies_after_callback():
        try:
            cookies = filter_market_cookies(await context.cookies(list(MARKET_COOKIE_URLS)))
            fresh = _has_fresh_market_session_cookie(cookies, baseline_session_values)
            _auth_trace(
                f"CALLBACK_READ names={sorted(c.get('name') for c in cookies)} "
                f"session={_has_market_session_cookie(cookies)} fresh={fresh}"
            )
            if fresh:
                captured_at_callback.append(cookies)
                callback_done.set()
        except Exception as exc:
            _auth_trace(f"CALLBACK_READ error={exc!r}")

    def _on_response(response):
        _state, is_callback = _classify_url(getattr(response, "url", ""))
        if AUTH_TRACE_ENABLED and (is_callback or _state in {"pa", "otp", "steam"}):
            path = urlparse(getattr(response, "url", "") or "").path
            _auth_trace(f"RESP {getattr(response, 'status', '?')} {path} state={_state} callback={is_callback}")
        if is_callback:
            asyncio.ensure_future(_read_market_cookies_after_callback())

    context_on = getattr(context, "on", None)
    if callable(context_on):
        context_on("response", _on_response)

    async def _poll_loop():
        nonlocal callback_seen, auth_flow_seen, pa_credentials_submitted
        nonlocal pa_cookie_consent_completed, last_trace_sig
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
                pa_cookie_consent_result = COOKIE_CONSENT_SKIPPED
                if not pa_cookie_consent_completed:
                    pa_cookie_consent_result = await _maybe_prepare_pa_cookie_consent(
                        page,
                        state,
                        tracking=pa_cookie_consent_state,
                        status_callback=status_callback,
                    )
                    if pa_cookie_consent_result in {COOKIE_CONSENT_SAVED, COOKIE_CONSENT_NOT_FOUND}:
                        pa_cookie_consent_completed = True
                        await _emit_callback(pa_cookie_consent_callback, pa_cookie_consent_result)

                auto_login_result = STEAM_AUTO_LOGIN_SKIPPED
                if _should_attempt_steam_auto_login(state, auth_flow_seen, callback_seen):
                    if pa_cookie_consent_result in {COOKIE_CONSENT_WAITING, COOKIE_CONSENT_MANUAL}:
                        auto_login_result = STEAM_AUTO_LOGIN_WAITING
                    else:
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
                pa_login_result = PA_AUTO_LOGIN_SKIPPED
                if not pa_credentials_submitted:
                    pa_login_result = await _maybe_run_pa_credentials_login(
                        page,
                        state,
                        enabled=auto_pa_login,
                        email=pa_email,
                        password=pa_password,
                        tracking=pa_auto_login_state,
                        status_callback=status_callback,
                        now=now,
                    )
                # Once credentials are submitted, stop re-attempting the fill. The post-submit
                # redirect pages (LoginProcess/AuthorizeOauth) still classify as "pa" but have no
                # login form, so retrying would block each poll on the fill timeout.
                if pa_login_result == PA_AUTO_LOGIN_SUBMITTED:
                    pa_credentials_submitted = True
                if pa_login_result in {PA_AUTO_LOGIN_SUBMITTED, PA_AUTO_LOGIN_MANUAL_NEEDED}:
                    auth_flow_seen = True

            cookies = filter_market_cookies(await context.cookies(list(MARKET_COOKIE_URLS)))
            if AUTH_TRACE_ENABLED:
                has_session = _has_market_session_cookie(cookies)
                fresh = _has_fresh_market_session_cookie(cookies, baseline_session_values)
                primary_url = urlparse(getattr(pages[0], "url", "") or "").path if pages else ""
                sig = (primary_url, market_active, auth_flow_seen, callback_seen, has_session, fresh)
                if sig != last_trace_sig:
                    last_trace_sig = sig
                    _auth_trace(
                        f"POLL url={primary_url} market={market_active} auth_flow={auth_flow_seen} "
                        f"cb={callback_seen} session={has_session} fresh={fresh} "
                        f"names={sorted(c.get('name') for c in cookies)}"
                    )
            if _market_cookie_capture_ready(cookies, baseline_session_values, callback_seen, market_active, auth_flow_seen):
                _auth_trace("CAPTURE via=poll")
                return cookies

            await asyncio.sleep(BROWSER_AUTH_POLL_SECONDS)

        _auth_trace("TIMEOUT")
        raise BrowserAuthError(f"{account_label} browser session timed out before Central Market cookies were captured.")

    # Run the polling loop and the OAuth-callback capture concurrently and finish on whichever
    # lands first. The callback capture can complete while the poll loop is parked in a slow,
    # navigation-blocked context.cookies() read, so it is watched independently here rather than
    # from inside the loop.
    poll_task = asyncio.ensure_future(_poll_loop())
    callback_task = asyncio.ensure_future(callback_done.wait())
    await asyncio.wait({poll_task, callback_task}, return_when=asyncio.FIRST_COMPLETED)

    if captured_at_callback:
        poll_task.cancel()
        callback_task.cancel()
        for task in (poll_task, callback_task):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        _auth_trace("CAPTURE via=callback")
        await _emit_status(
            status_callback,
            "Marketplace cookies captured at login callback. Closing browser before validation.",
            "info",
        )
        return captured_at_callback[0]

    callback_task.cancel()
    try:
        await callback_task
    except (asyncio.CancelledError, Exception):
        pass
    return poll_task.result()


async def _close_browser_context(context, status_callback=None):
    pages = [page for page in getattr(context, "pages", []) or [] if not _page_is_closed(page)]
    if pages:
        await asyncio.gather(*[_close_page_quickly(page) for page in pages], return_exceptions=True)

    try:
        await asyncio.wait_for(context.close(), timeout=BROWSER_CONTEXT_CLOSE_TIMEOUT_SECONDS)
    except Exception:
        await _emit_status(
            status_callback,
            "Browser cookies were captured, but Chrome did not close cleanly. Close it manually if it remains open.",
            "warning",
        )


async def _close_page_quickly(page):
    close_page = getattr(page, "close", None)
    if close_page is None:
        return
    try:
        close_result = close_page(run_before_unload=False)
    except TypeError:
        close_result = close_page()
    except Exception:
        return

    if inspect.isawaitable(close_result):
        try:
            await asyncio.wait_for(close_result, timeout=BROWSER_PAGE_CLOSE_TIMEOUT_SECONDS)
        except Exception:
            pass


async def _bootstrap_browser_profile(page, status_callback, bootstrap_url, account_label):
    try:
        await _emit_status(
            status_callback,
            f"Preparing {account_label} browser profile from the Black Desert site.",
            "info",
        )
        await page.goto(bootstrap_url, wait_until="domcontentloaded", timeout=60000)
        await _accept_required_cookie_consent_if_available(
            page,
            status_callback,
            profile_label=f"{account_label} browser profile",
        )
    except Exception:
        await _emit_status(
            status_callback,
            f"{account_label} browser profile preparation was skipped; continuing to marketplace login.",
            "warning",
        )


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


async def _wait_for_cookie_consent_manual_completion(page, context):
    while True:
        pages = [open_page for open_page in context.pages if not _page_is_closed(open_page)]
        if not pages:
            raise BrowserAuthError("Initial Steam setup was closed before the browser profile was prepared.")
        if _page_is_closed(page):
            raise BrowserAuthError("Initial Steam setup page was closed before the browser profile was prepared.")
        if await _cookiebot_dialog_hidden(page):
            return
        await asyncio.sleep(STEAM_PROFILE_SETUP_POLL_SECONDS)


async def _wait_for_steam_profile_login(context, status_callback, timeout_seconds):
    deadline = asyncio.get_running_loop().time() + float(timeout_seconds)
    while asyncio.get_running_loop().time() < deadline:
        pages = [page for page in context.pages if not _page_is_closed(page)]
        if not pages:
            raise BrowserAuthError("Steam setup browser closed before Steam login was detected.")

        if _has_steam_login_cookie(await context.cookies(list(STEAM_PROFILE_COOKIE_URLS))):
            await _emit_status(status_callback, "Steam login detected in the browser profile.", "info")
            return

        for page in pages:
            if await _steam_store_logged_in_dom_ready(page):
                await _emit_status(status_callback, "Steam login detected in the browser profile.", "info")
                return

        await asyncio.sleep(STEAM_PROFILE_SETUP_POLL_SECONDS)

    raise BrowserAuthError("Steam setup timed out before Steam login was detected.")


def _has_steam_login_cookie(cookies):
    for cookie in cookies or []:
        if not isinstance(cookie, dict):
            continue
        if cookie.get("name") in STEAM_LOGIN_COOKIE_NAMES:
            return True
    return False


async def _steam_store_logged_in_dom_ready(page):
    if urlparse(getattr(page, "url", "") or "").hostname != "store.steampowered.com":
        return False
    for selector in STEAM_LOGGED_IN_SELECTORS:
        try:
            if await page.locator(selector).first.is_visible(timeout=500):
                return True
        except Exception:
            continue
    return False


async def _accept_required_cookie_consent_if_available(page, status_callback=None, *, profile_label="Steam browser profile"):
    if not await _cookiebot_dialog_visible(page):
        return COOKIE_CONSENT_NOT_FOUND

    for selector in COOKIEBOT_REQUIRED_CONSENT_SELECTORS:
        try:
            await page.locator(selector).first.click(timeout=COOKIEBOT_CONSENT_CLICK_TIMEOUT_MS)
        except Exception:
            continue

        if await _cookiebot_dialog_hidden(page):
            await _emit_status(status_callback, f"Required cookie consent saved in the {profile_label}.", "info")
            return COOKIE_CONSENT_SAVED
        else:
            await _emit_status(
                status_callback,
                "Required cookie consent click sent; continue manually if the banner remains.",
                "info",
            )
            return COOKIE_CONSENT_MANUAL
    return COOKIE_CONSENT_NOT_FOUND


async def _cookiebot_dialog_visible(page):
    try:
        await page.locator(COOKIEBOT_DIALOG_SELECTOR).wait_for(
            state="visible",
            timeout=COOKIEBOT_DIALOG_DETECTION_TIMEOUT_MS,
        )
        return True
    except Exception:
        return False


def _new_steam_auto_login_state():
    return {
        "clicked": set(),
        "missing_started_at": {},
        "missing_reported": set(),
    }


def _new_pa_auto_login_state():
    return {
        "submitted": set(),
        "missing_started_at": {},
        "missing_reported": set(),
    }


def _new_pa_cookie_consent_state():
    return {
        "checked": set(),
    }


def _should_attempt_steam_auto_login(state, auth_flow_seen, callback_seen):
    if state == "market" and (auth_flow_seen or callback_seen):
        return False
    return True


async def _maybe_prepare_pa_cookie_consent(
    page,
    state,
    *,
    tracking,
    status_callback=None,
):
    targets = _pa_cookie_consent_targets(page, state)
    if not targets:
        return COOKIE_CONSENT_SKIPPED

    result = COOKIE_CONSENT_SKIPPED
    for scope in targets:
        scope_result = await _maybe_prepare_pa_cookie_consent_target(
            scope,
            tracking=tracking,
            status_callback=status_callback,
        )
        if scope_result in {COOKIE_CONSENT_SAVED, COOKIE_CONSENT_NOT_FOUND, COOKIE_CONSENT_MANUAL}:
            return scope_result
        if scope_result == COOKIE_CONSENT_WAITING:
            result = COOKIE_CONSENT_WAITING

    return result


async def _maybe_prepare_pa_cookie_consent_target(scope, *, tracking, status_callback=None):
    key = (id(scope), "pa_cookie_consent", getattr(scope, "url", ""))
    if key in tracking["checked"]:
        return COOKIE_CONSENT_SKIPPED

    # Lean on the Steam login button being actually clickable. A trial click runs Playwright's
    # full actionability checks — including "receives pointer events", i.e. not occluded — so
    # when no consent banner is overlaying it, this returns immediately and we skip the slower
    # cookie-dialog probe entirely. If a banner is covering the button the trial click fails and
    # we fall through to dismiss it, so a blocked button can never be mistaken for ready.
    if await _selector_clickable(scope, PA_STEAM_LOGIN_SELECTORS, timeout=PA_CONSENT_BUTTON_READY_TIMEOUT_MS):
        tracking["checked"].add(key)
        return COOKIE_CONSENT_NOT_FOUND

    consent_result = await _accept_required_cookie_consent_if_available(
        scope,
        status_callback,
        profile_label="Pearl Abyss login page",
    )
    if consent_result == COOKIE_CONSENT_SAVED:
        tracking["checked"].add(key)
        return COOKIE_CONSENT_SAVED
    if consent_result == COOKIE_CONSENT_MANUAL:
        return COOKIE_CONSENT_MANUAL

    return COOKIE_CONSENT_WAITING


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


async def _maybe_run_pa_credentials_login(
    page,
    state,
    *,
    enabled,
    email,
    password,
    tracking,
    status_callback=None,
    now=None,
    missing_notice_seconds=PA_AUTO_LOGIN_MISSING_NOTICE_SECONDS,
):
    if not enabled or not email or not password:
        return PA_AUTO_LOGIN_DISABLED

    targets = _pa_credentials_login_targets(page, state)
    if not targets:
        return PA_AUTO_LOGIN_SKIPPED

    now = asyncio.get_running_loop().time() if now is None else now
    result = PA_AUTO_LOGIN_SKIPPED
    for scope in targets:
        scope_result = await _maybe_run_pa_credentials_login_target(
            scope,
            email,
            password,
            tracking=tracking,
            status_callback=status_callback,
            now=now,
            missing_notice_seconds=missing_notice_seconds,
        )
        if scope_result in {PA_AUTO_LOGIN_SUBMITTED, PA_AUTO_LOGIN_MANUAL_NEEDED}:
            return scope_result
        if scope_result == PA_AUTO_LOGIN_WAITING:
            result = PA_AUTO_LOGIN_WAITING

    return result


async def _maybe_run_pa_credentials_login_target(
    scope,
    email,
    password,
    *,
    tracking,
    status_callback,
    now,
    missing_notice_seconds,
):
    key = (id(scope), "pa_credentials_login", getattr(scope, "url", ""))
    if key in tracking["submitted"]:
        return PA_AUTO_LOGIN_SKIPPED

    credentials_filled = await _fill_pa_credentials(scope, email, password)
    if credentials_filled and await _click_first_available_selector(
        scope,
        PA_LOGIN_BUTTON_SELECTORS,
        timeout=PA_AUTO_LOGIN_CLICK_TIMEOUT_MS,
    ):
        tracking["submitted"].add(key)
        tracking["missing_started_at"].pop(key, None)
        await _emit_status(status_callback, "Automatic Pearl Abyss login submitted saved credentials.", "info")
        return PA_AUTO_LOGIN_SUBMITTED

    started_at = tracking["missing_started_at"].setdefault(key, now)
    if now - started_at >= missing_notice_seconds and key not in tracking["missing_reported"]:
        tracking["missing_reported"].add(key)
        await _emit_status(
            status_callback,
            "Automatic Pearl Abyss login is waiting for manual input on the Pearl Abyss page.",
            "warning",
        )
        return PA_AUTO_LOGIN_MANUAL_NEEDED

    return PA_AUTO_LOGIN_WAITING


async def _fill_pa_credentials(scope, email, password):
    email_filled = await _fill_first_available_selector(
        scope,
        PA_EMAIL_SELECTORS,
        str(email),
        timeout=PA_AUTO_LOGIN_FILL_TIMEOUT_MS,
    )
    if not email_filled:
        return False
    return await _fill_first_available_selector(
        scope,
        PA_PASSWORD_SELECTORS,
        str(password),
        timeout=PA_AUTO_LOGIN_FILL_TIMEOUT_MS,
    )


def _pa_credentials_login_targets(page, state):
    targets = []
    seen = set()

    def add_target(scope, target_state):
        if target_state != "pa":
            return
        key = id(scope)
        if key in seen:
            return
        seen.add(key)
        targets.append(scope)

    add_target(page, _pa_credentials_login_target_state(state))
    for frame in getattr(page, "frames", []) or []:
        frame_state, _is_callback = _classify_url(getattr(frame, "url", ""))
        add_target(frame, _pa_credentials_login_target_state(frame_state))

    return targets


def _pa_credentials_login_target_state(state):
    if state == "pa":
        return "pa"
    if state is None:
        return "pa"
    return None


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


def _pa_cookie_consent_targets(page, state):
    targets = []
    seen = set()

    def add_target(scope, target_state):
        if target_state != "pa":
            return
        key = id(scope)
        if key in seen:
            return
        seen.add(key)
        targets.append(scope)

    add_target(page, _pa_cookie_consent_target_state(state))
    for frame in getattr(page, "frames", []) or []:
        frame_state, _is_callback = _classify_url(getattr(frame, "url", ""))
        add_target(frame, _pa_cookie_consent_target_state(frame_state))

    return targets


def _pa_cookie_consent_target_state(state):
    if state == "pa":
        return "pa"
    return None


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


async def _selector_clickable(page, selectors, timeout):
    for selector in selectors:
        try:
            # trial=True runs actionability checks (visible, stable, enabled, not occluded)
            # without performing the click, so an element under a consent overlay fails here.
            await page.locator(selector).first.click(trial=True, timeout=timeout)
            return True
        except Exception:
            continue
    return False


async def _fill_first_available_selector(page, selectors, value, timeout):
    for selector in selectors:
        try:
            await page.locator(selector).first.fill(value, timeout=timeout)
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


def _has_market_session_cookie(cookies):
    return any(cookie.get("name") in MARKET_SESSION_COOKIE_NAMES for cookie in cookies or [])


def _market_session_cookie_values(cookies):
    values = set()
    for cookie in cookies or []:
        if cookie.get("name") in MARKET_SESSION_COOKIE_NAMES:
            value = cookie.get("value")
            if value:
                values.add(value)
    return values


def _has_fresh_market_session_cookie(cookies, baseline_session_values):
    for cookie in cookies or []:
        if cookie.get("name") in MARKET_SESSION_COOKIE_NAMES:
            value = cookie.get("value")
            if value and value not in baseline_session_values:
                return True
    return False


def _market_cookie_capture_ready(cookies, baseline_session_values, callback_seen, market_active, auth_flow_seen):
    if not _has_market_session_cookie(cookies):
        return False

    # Fast path: an auth flow happened and a *new* marketplace session cookie was issued. This
    # fires the moment login completes (the cookie is set on the OAuth callback) instead of
    # waiting for the heavy market page to load, and it can never trip on a stale pre-login
    # cookie because the value must differ from the pre-login baseline.
    if (auth_flow_seen or callback_seen) and _has_fresh_market_session_cookie(cookies, baseline_session_values):
        return True

    # Saved browser session was still valid: the market loaded with no auth detour, so the
    # existing session cookie is the live one. An expired profile would have redirected to the
    # login page first (auth_flow_seen), so this never captures a stale session.
    if market_active and not auth_flow_seen:
        return True

    return False


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


async def _emit_callback(callback, *args):
    if callback is None:
        return
    result = callback(*args)
    if inspect.isawaitable(result):
        await result
