# Marketplace Tools

## Project Status

This project is currently undergoing a codebase rewrite and Textual UI migration. Features may be incomplete, unstable, or temporarily broken while the modernization work is in progress.

## Disclaimer

This repository is provided as a proof of concept for authenticated web sessions, HTTP requests, and marketplace-style API integration. Use it only in environments where automation is permitted by the relevant terms of service. The project does not handle CAPTCHA challenges or other access-control interruptions.

## Supported Versions

Last verified against the supported marketplace flow: July 14, 2025.

Steam accounts and OTP-enabled accounts are not supported. Only launcher accounts without OTP are supported.

## About the Project

Marketplace Tools is a Python terminal app for monitoring the *Black Desert Online* marketplace from an authenticated session. It demonstrates how to maintain a login session, inspect marketplace availability through HTTP requests, decode marketplace responses, and run a configurable long-lived monitor.

The project covers browser network analysis, request payload debugging, session persistence, and resilient terminal-app design.

## How It Works

When enabled, the app periodically checks outfit marketplace categories using a preset or custom delay window. The default mode is watch-only, which reports availability without submitting purchase requests and can run without logging in. A separate buy mode can be enabled from the dashboard monitor controls and requires an authenticated session plus confirmation before the monitor starts.

The app uses your login credentials to authenticate with the official [BDO web marketplace](https://na-trade.naeu.playblackdesert.com/Intro/). The email is stored locally, while the password is stored through the operating system keyring. The app can also persist and reuse marketplace sessions, then re-authenticate when a session expires.

## Launch Modes

Default launch mode checks the saved marketplace session on startup. For interface work or local testing where that startup API call should be skipped, launch with test mode:

```powershell
run-test.bat
run.bat --test-mode
py -3 main.py --test-mode
```

You can also set `BDO_MARKET_TEST_MODE=1`. Test mode skips only the automatic startup session check; explicit actions such as session refresh, wallet refresh, or starting the monitor can still call live marketplace endpoints.

In test mode, extra sidebar controls are available for interface and debug work: adding synthetic event-log rows, toggling a simulated valid session, faking a watch-only outfit detection, and simulating purchase accounting without calling the live buy API.

## Technical Highlights

- Python async terminal app with long-running background tasks.
- Textual-powered terminal UI with live status widgets, sidebar navigation, and event logging.
- Authenticated HTTP session management with `requests`.
- Marketplace response decoding using a Huffman decoder.
- Configurable preset or custom polling delay windows.
- Watch-only mode, buy mode, and spend caps.
- Local session persistence and automatic re-login flow.
- Local dashboard statistics for successful purchases and silver spent.
- Test-mode simulation tools for event-log sizing and purchase-success-rate checks.
- OS keyring integration for safer password storage.

## Known Issues

If your IP reputation is low, the official login flow may present a CAPTCHA. This project does not handle CAPTCHA challenges. To confirm whether that is the issue, try logging in manually on the [BDO website](https://www.naeu.playblackdesert.com/en-US/Main/Index).

If you encounter `unexpected result code 34` when attempting to make a purchase, it usually means the outfit went out of stock before the request completed, or the request would create a duplicate pre-order.

`unexpected result code -14` means price mismatch. This can happen when Pearl Abyss changes max prices or when an item has not reached its max price yet.

## Credits

`decoder.py` is based on work by [shrddr](https://github.com/shrddr/huffman_heap).

## Contact

For questions or bug reports, use the project issue tracker or the listed Discord contact: `._.__.__._._.__._____.__._.___.`

## Planned Work

- Steam account compatibility.
- More configurable marketplace categories.
