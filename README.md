# Marketplace Tools

## Project Status

This project is currently undergoing a codebase rewrite and Textual UI migration. Features may be incomplete, unstable, or temporarily broken while the modernization work is in progress.

## Disclaimer

This project is a personal proof of concept for learning authenticated web sessions, HTTP requests, and marketplace-style API integration. Use it only in environments where automation is permitted by the relevant terms of service. The project does not handle CAPTCHA challenges or other access-control interruptions.

## Supported Versions

Last verified: July 14, 2025. If you are having problems, please message me on Discord (see below).

Currently, Steam accounts and OTP-enabled accounts are not supported. Only launcher accounts without OTP are supported. Steam support is a work in progress.

## About the Project

Marketplace Tools is a Python terminal app for monitoring the *Black Desert Online* marketplace from an authenticated session. It demonstrates how to maintain a login session, inspect marketplace availability through HTTP requests, decode marketplace responses, and run a configurable long-lived monitor.

The project began as a practical exercise in browser network analysis, request payload debugging, session persistence, and resilient terminal-app design.

## How It Works

When enabled, the app periodically checks outfit marketplace categories using a preset or custom delay window. The default mode is watch-only, which reports availability without submitting purchase requests and can run without logging in. A separate buy mode can be enabled from the dashboard monitor controls and requires an authenticated session plus confirmation before the monitor starts.

The app uses your login credentials to authenticate with the official [BDO web marketplace](https://na-trade.naeu.playblackdesert.com/Intro/). The email is stored locally, while the password is stored through the operating system keyring. The app can also persist and reuse marketplace sessions, then re-authenticate when a session expires.

## Launch Modes

Default launch mode checks the saved marketplace session on startup. For UI work or local testing where you do not want that startup API call, launch with test mode:

```powershell
run.bat --test-mode
py -3 main.py --test-mode
```

You can also set `BDO_MARKET_TEST_MODE=1` or use `run-test.bat`. Test mode skips only the automatic startup session check; explicit actions such as session refresh, wallet refresh, or starting the monitor can still call live marketplace endpoints.

In test mode, extra sidebar controls are available for UI/debug work: adding synthetic event-log rows, faking a watch-only outfit detection, and simulating a detection plus successful purchase accounting without calling the live buy API.

## Technical Highlights

- Python async terminal app with long-running background tasks.
- Textual-powered terminal UI with live dashboard tiles, dashboard control modals, app-level sidebar navigation, and event logging.
- Authenticated HTTP session management with `requests`.
- Marketplace response decoding using a Huffman decoder.
- Configurable preset or custom polling delay windows from the dashboard polling modal.
- Watch-only mode, buy mode, and spend caps.
- Local session persistence and automatic re-login flow.
- Local dashboard statistics for successful purchases and silver spent.
- Test-mode simulation tools for event-log sizing and purchase-success-rate checks.
- OS keyring integration for safer password storage.

## Known Issues

If your IP reputation is low, the official login flow may present a CAPTCHA. This project does not handle CAPTCHA challenges. To confirm whether that is the issue, try logging in manually on the [BDO website](https://www.naeu.playblackdesert.com/en-US/Main/Index).

If you encounter `unexpected result code 34` when attempting to make a purchase, it usually means the outfit went out of stock before the request completed, or the request would create a duplicate pre-order.

`unexpected result code -14` means price mismatch. This can happen when Pearl Abyss changes max prices or when an item has not reached its max price yet.

## Resume-Friendly Summary

**Marketplace Tools | Python, HTTP Requests, REST APIs**

- Built a Python terminal app for authenticated marketplace monitoring using HTTP requests, configurable polling windows, safety limits, and long-running background tasks.
- Analyzed browser network traffic to identify API endpoints, request payloads, response formats, and authentication/session patterns.
- Implemented session persistence, automatic re-authentication, compressed response decoding, Textual terminal dashboards, event logging, and safer local credential handling through the OS keyring.

## Credits

`decoder.py` is based on work by [shrddr](https://github.com/shrddr/huffman_heap).

## Contact Me

For questions or bug reports, please message me on Discord: `._.__.__._._.__._____.__._.___.`

## WIP / TODO

- Steam account compatibility.
- More configurable marketplace categories.
