# Marketplace Tools

![Marketplace Tools dashboard](docs/assets/dashboard.png)

## About the Project

Marketplace Tools is a Python terminal app for monitoring the *Black Desert Online* marketplace from an authenticated session. It demonstrates how to maintain a marketplace login session, inspect outfit availability through HTTP requests, decode marketplace responses, and run a configurable long-lived monitor.

The app is designed around safety-first defaults: watch-only monitoring is the normal starting point, while buy mode must be explicitly enabled and confirmed before authenticated purchase requests are submitted.

## How It Works

The monitor checks the public outfit marketplace categories on a configurable polling window. It pulls the male and female outfit subcategories concurrently, decodes the packed marketplace response, and filters rows with available stock.

When running in watch-only mode, detections are written to the dashboard event log without making purchase requests. When buy mode is enabled, detections pass through outfit price rules, the current spend cap, and a configurable delay between individual buy attempts.

Authenticated requests use a saved marketplace cookie session when available. The app can refresh session validity, re-authenticate with saved credentials when needed, and record successful purchases using the actual price returned by the marketplace API.

## Technical Highlights

- Textual-powered terminal dashboard with live monitor, session, spend, polling, buy-delay, and event-log widgets.
- Concurrent public marketplace scans for outfit categories.
- Marketplace response decoding using a Huffman decoder.
- Authenticated HTTP session management with `requests`.
- Cookie-based session persistence under ignored local runtime files.
- OS keyring integration for password storage.
- Watch-only mode, confirmed buy mode, spend caps, and configurable buy delay.
- Purchase accounting based on structured API responses instead of guessed success strings.
- Local dashboard statistics for successful purchases and silver spent.
- Focused tests for session handling, scan parsing, pricing rules, spend caps, buy results, and UI behavior.

## Project Status

This project is currently undergoing a codebase rewrite and Textual UI migration. Features may be incomplete, unstable, or temporarily broken while the modernization work is in progress.

## Supported Versions

Last verified against the supported marketplace flow: July 14, 2025.

Steam accounts and OTP-enabled accounts are not supported. Only launcher accounts without OTP are supported.

## Running the App

On Windows, run:

```powershell
run.bat
```

Or run directly from the repository root:

```powershell
py -3 main.py
```

`run.bat` uses Windows Terminal when available so the Textual UI opens at a usable size. Set `BDO_DISABLE_WT=1` before launching to run in the current console instead.

## Disclaimer

This repository is provided as a proof of concept for authenticated web sessions, HTTP requests, and marketplace-style API integration. Use it only in environments where automation is permitted by the relevant terms of service. The project does not handle CAPTCHA challenges or other access-control interruptions.

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
