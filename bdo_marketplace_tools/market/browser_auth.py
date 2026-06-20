import asyncio
import inspect
from pathlib import Path
from urllib.parse import urlparse

from bdo_marketplace_tools.market.api_handler import GAME_TRADE_URL, TRADE_URL
from bdo_marketplace_tools.storage.paths import (
    STEAM_MARKET_DIAGNOSTIC_PROFILE_PATH,
    STEAM_MARKET_PROFILE_PATH,
)


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
# A Steam login button click can "succeed" (Playwright sees the element as actionable) without
# firing the page's js-btnLastLoginCheck handler if that handler has not bound yet -- common right
# after the Cookiebot banner is dismissed and the page re-renders. A working click navigates away
# within this grace (changing the URL, so the key below is never revisited); only if the page has
# still not advanced after the grace do we treat the click as dead and re-click. The grace is kept
# longer than a normal click's navigation latency so a slow-but-working click is never re-clicked
# mid-navigation. Re-click up to a capped number of attempts before asking the user to finish.
STEAM_AUTO_LOGIN_RETRY_AFTER_SECONDS = 1.5
STEAM_AUTO_LOGIN_MAX_CLICK_ATTEMPTS = 4
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
# Cookie domains whose cookies are preserved when dumping everything else (test tooling): the full
# Steam web session lives across these domains (steamLoginSecure, sessionid, steamMachineAuth, ...),
# and keeping all of them avoids having to log back into Steam between re-auth test runs.
STEAM_AUTH_COOKIE_DOMAIN_SUFFIXES = (
    "steampowered.com",
    "steamcommunity.com",
    "steam-chat.com",
)
STEAM_LOGGED_IN_SELECTORS = (
    "#account_pulldown",
    ".user_avatar",
)
# Visible verification-challenge (CAPTCHA) widgets that can appear on the Pearl Abyss / Steam
# login pages. Detection is deliberately conservative and visibility-gated: it must only fire on
# an interactive challenge the user has to solve, never on the passive reCAPTCHA v3 badge
# (`.grecaptcha-badge`), which renders on countless pages with nothing to solve and would be a
# constant false positive. This is a best-effort starting set; extend it the first time a real
# challenge selector is observed in the wild (we have no captcha to test against yet).
AUTH_CHALLENGE_SELECTORS = (
    "iframe[src*='hcaptcha.com']",
    ".h-captcha",
    "iframe[src*='challenges.cloudflare.com']",
    ".cf-turnstile",
    ".g-recaptcha",
    "iframe[src*='recaptcha'][src*='bframe']",
)
AUTH_CHALLENGE_DETECTION_TIMEOUT_MS = 150
# Only the live auth pages can present a challenge the user must solve; never probe the market page.
AUTH_CHALLENGE_STATES = {"pa", "steam", "otp"}

# A purely cosmetic notice injected into the visible browser during first-time setup (only while the
# app is auto-driving the cookie-consent + Steam-login flow, which is the one-time slower path). It
# reassures the user not to click while the automation works. `pointer-events:none` means it can
# never intercept a click, and add_init_script re-shows it on every navigation in the flow.
FIRST_TIME_SETUP_NOTICE_SCRIPT = r"""
(() => {
  const ID = '__bdo_first_time_setup_notice__';
  const STYLE_ID = '__bdo_first_time_setup_notice_style__';
  const ensureStyle = () => {
    if (document.getElementById(STYLE_ID)) return;
    const st = document.createElement('style');
    st.id = STYLE_ID;
    st.textContent = '@keyframes __bdoSetupSpin{to{transform:rotate(360deg)}}';
    (document.head || document.documentElement).appendChild(st);
  };
  const show = () => {
    if (!document.body || document.getElementById(ID)) return;
    ensureStyle();
    const card = document.createElement('div');
    card.id = ID;
    card.setAttribute('style', [
      'position:fixed','top:20px','left:50%','transform:translateX(-50%)',
      'z-index:2147483647','pointer-events:none','box-sizing:border-box',
      'max-width:520px','width:calc(100% - 32px)','padding:14px 24px',
      'border-radius:14px','border:1px solid #2e2e2e',
      'background:#141414','color:#cfccc4','text-align:center',
      "font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif",
      'box-shadow:0 8px 26px rgba(0,0,0,0.45)',
      'opacity:0','transition:opacity .4s ease'
    ].join(';'));
    card.innerHTML =
      '<div style="display:flex;align-items:center;justify-content:center;gap:10px;">' +
        '<span style="box-sizing:border-box;width:15px;height:15px;border-radius:50%;' +
          'border:2px solid rgba(255,145,60,0.3);border-top-color:#ff913c;' +
          'animation:__bdoSetupSpin 0.7s linear infinite;"></span>' +
        '<span style="font-size:15px;font-weight:600;color:#ff913c;letter-spacing:.2px;">' +
          'First-time setup in progress' +
        '</span>' +
      '</div>' +
      '<div style="font-size:13px;font-weight:400;margin-top:6px;opacity:.92;line-height:1.5;">' +
        'This one-time step can take a little longer. Please don’t click anything — ' +
        'it will finish on its own.' +
      '</div>';
    document.body.appendChild(card);
    requestAnimationFrame(() => { card.style.opacity = '1'; });
  };
  if (document.body) show();
  else document.addEventListener('DOMContentLoaded', show);
})();
"""


async def _inject_first_time_setup_notice(context):
    # Best-effort: never let a cosmetic notice break the auth flow if the runtime lacks the API.
    add_init_script = getattr(context, "add_init_script", None)
    if not callable(add_init_script):
        return
    try:
        await add_init_script(FIRST_TIME_SETUP_NOTICE_SCRIPT)
    except Exception:
        pass


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
                if handle_pa_cookie_consent:
                    # First-time setup (cookie consent still being handled, auto-login driving): show
                    # a non-blocking notice so the user doesn't fight the automation. Added before
                    # the first navigation so it appears on every page of the flow.
                    await _inject_first_time_setup_notice(context)
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


def _is_steam_auth_cookie(cookie):
    if not isinstance(cookie, dict):
        return False
    domain = (cookie.get("domain") or "").lstrip(".").lower()
    if not domain:
        return False
    return any(
        domain == suffix or domain.endswith("." + suffix)
        for suffix in STEAM_AUTH_COOKIE_DOMAIN_SUFFIXES
    )


async def clear_market_cookies_keep_steam_login(
    *,
    profile_path=STEAM_MARKET_PROFILE_PATH,
):
    """Clear every cookie in the profile except the Steam web session cookies.

    Test tooling: leaves the user logged into Steam while wiping the marketplace session, the
    Pearl Abyss session, and the Cookiebot consent cookie, so the next re-auth runs the full
    cookie-box + Steam-button flow without a Steam re-login. Returns the number of cookies cleared.
    """
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
            all_cookies = await context.cookies()
            kept = [cookie for cookie in all_cookies if _is_steam_auth_cookie(cookie)]
            await context.clear_cookies()
            if kept:
                await context.add_cookies(kept)
            return len(all_cookies) - len(kept)
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

    # The marketplace session cookie the app needs (TradeAuth_Session) is set on the
    # /Pearlabyss/Oauth2CallBack 302. That redirect never becomes page.url, so URL polling can't
    # observe it, and the poll loop's own context.cookies() read blocks for several seconds while
    # the market page navigates after login. So we read cookies the instant the callback *response*
    # arrives and race that capture against the poll loop (below), closing at login success instead
    # of after the market page loads. (__RequestVerificationToken lands later, at the market page,
    # but the app's authenticated calls do not require it.)
    captured_at_callback = []
    callback_done = asyncio.Event()
    async def _read_market_cookies_after_callback():
        try:
            cookies = filter_market_cookies(await context.cookies(list(MARKET_COOKIE_URLS)))
            if _has_fresh_market_session_cookie(cookies, baseline_session_values):
                captured_at_callback.append(cookies)
                callback_done.set()
        except Exception:
            pass

    def _on_response(response):
        _state, is_callback = _classify_url(getattr(response, "url", ""))
        if is_callback:
            asyncio.ensure_future(_read_market_cookies_after_callback())

    context_on = getattr(context, "on", None)
    if callable(context_on):
        context_on("response", _on_response)

    async def _poll_loop():
        nonlocal callback_seen, auth_flow_seen, pa_credentials_submitted
        nonlocal pa_cookie_consent_completed
        # A verification challenge (CAPTCHA) blocks login until a human solves it. Track it so the
        # warning is emitted once per appearance (edge-triggered) and the timeout message can say
        # verification was never completed instead of giving a generic "no cookies" error.
        challenge_notified = False
        challenge_ever_seen = False
        while asyncio.get_running_loop().time() < deadline:
            now = asyncio.get_running_loop().time()
            pages = [page for page in context.pages if not _page_is_closed(page)]
            if not pages:
                raise BrowserAuthError("Browser closed before a marketplace session could be captured.")

            market_active = False
            challenge_active = False
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

                # If a CAPTCHA/challenge is on screen, stop the automation from poking the page
                # (clicking login / submitting credentials on an active anti-bot challenge is the
                # worst time to keep acting) and let the visible window wait for the human.
                page_challenge = await _auth_challenge_visible(page, state)
                if page_challenge:
                    challenge_active = True
                    challenge_ever_seen = True
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
                if not page_challenge and _should_attempt_steam_auto_login(state, auth_flow_seen, callback_seen):
                    # Skip the Steam auto-click on the same iteration the banner was just handled
                    # (the page is mid-teardown/re-render); the next poll clicks. If that first
                    # click lands before the button's js-btnLastLoginCheck handler rebinds, the
                    # auto-login retries it (see _maybe_run_steam_auto_login_target) rather than
                    # marking a dead click done forever.
                    if pa_cookie_consent_result in {
                        COOKIE_CONSENT_WAITING,
                        COOKIE_CONSENT_MANUAL,
                        COOKIE_CONSENT_SAVED,
                    }:
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
                if not pa_credentials_submitted and not page_challenge:
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

            # Edge-triggered: announce a challenge once when it appears, and re-arm when it clears
            # so a second, later challenge is announced again rather than swallowed.
            if challenge_active and not challenge_notified:
                challenge_notified = True
                await _emit_status(status_callback, _auth_challenge_message(account_label), "warning")
            elif not challenge_active:
                challenge_notified = False

            cookies = filter_market_cookies(await context.cookies(list(MARKET_COOKIE_URLS)))
            if _market_cookie_capture_ready(cookies, baseline_session_values, callback_seen, market_active, auth_flow_seen):
                return cookies

            await asyncio.sleep(BROWSER_AUTH_POLL_SECONDS)

        if challenge_ever_seen:
            raise BrowserAuthError(
                f"{account_label} browser session timed out before verification was completed. "
                "Complete the CAPTCHA/verification in the browser, then refresh the session again."
            )
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
        "clicked_at": {},
        "click_count": {},
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

    # Probe for the Cookiebot banner FIRST, then confirm the Steam button. Do NOT reorder this to
    # "check the button first" as a speed optimization: the Cookiebot banner is injected by an
    # async third-party script and routinely appears *after* the Steam button is already in the
    # DOM. Checking the button first races that injection — in the gap before the banner loads the
    # button looks ready, so consent is marked done and the dismissal is skipped, then the banner
    # appears and blocks the real Steam login click. `_cookiebot_dialog_visible` waits up to
    # COOKIEBOT_DIALOG_DETECTION_TIMEOUT_MS for the banner so a slightly-late banner is still
    # caught and dismissed.
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

    if await _selector_visible(scope, PA_STEAM_LOGIN_SELECTORS, timeout=PA_CONSENT_BUTTON_READY_TIMEOUT_MS):
        tracking["checked"].add(key)
        return COOKIE_CONSENT_NOT_FOUND

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
    # The url is part of the key on purpose: a click that actually works navigates away, producing
    # a different key, so we only ever revisit this key while the page has NOT advanced.
    key = (id(scope), selector_key, getattr(scope, "url", ""))

    last_click_at = tracking["clicked_at"].get(key)
    if last_click_at is not None:
        # Already clicked this button on this exact page. A working click navigates away within this
        # grace (changing the URL, so this key is never revisited); only if the page has still not
        # advanced after the grace do we treat it as a dead click and re-click, up to the cap.
        if now - last_click_at < STEAM_AUTO_LOGIN_RETRY_AFTER_SECONDS:
            return STEAM_AUTO_LOGIN_WAITING
        if tracking["click_count"].get(key, 0) >= STEAM_AUTO_LOGIN_MAX_CLICK_ATTEMPTS:
            if key not in tracking["missing_reported"]:
                tracking["missing_reported"].add(key)
                await _emit_status(status_callback, missing_message, "warning")
                return STEAM_AUTO_LOGIN_MANUAL_NEEDED
            return STEAM_AUTO_LOGIN_WAITING

    if await _click_first_available_selector(scope, selectors, timeout=STEAM_AUTO_LOGIN_CLICK_TIMEOUT_MS):
        first_click = last_click_at is None
        tracking["clicked_at"][key] = now
        tracking["click_count"][key] = tracking["click_count"].get(key, 0) + 1
        tracking["missing_started_at"].pop(key, None)
        if first_click:
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


async def _selector_visible(page, selectors, timeout):
    for selector in selectors:
        try:
            if await page.locator(selector).first.is_visible(timeout=timeout):
                return True
        except Exception:
            continue
    return False


async def _auth_challenge_visible(page, state):
    if state not in AUTH_CHALLENGE_STATES:
        return False
    return await _selector_visible(page, AUTH_CHALLENGE_SELECTORS, timeout=AUTH_CHALLENGE_DETECTION_TIMEOUT_MS)


def _auth_challenge_message(account_label):
    return (
        f"Verification challenge (CAPTCHA) detected on the {account_label} login page. "
        "Automatic login is paused — complete the verification in the open browser window. "
        "Login will continue automatically once it is solved."
    )


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
