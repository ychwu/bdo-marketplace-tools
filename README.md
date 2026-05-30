# Marketplace Tools

![Marketplace Tools dashboard](docs/assets/dashboard.png)


Marketplace Tools is a Python CLI app for monitoring the *Black Desert Online* marketplace from an authenticated session. It demonstrates how to maintain a marketplace login session, inspect outfit availability through HTTP requests, decode marketplace responses, and run a configurable long-lived monitor.

The app is designed around safety-first defaults: watch-only monitoring is the normal starting point, while buy mode must be explicitly enabled and confirmed before authenticated purchase requests are submitted.

## Features

### Core Capabilities

- Monitors Black Desert Online marketplace outfit listings from a terminal dashboard.
- Runs in watch-only mode by default so availability can be tracked without submitting purchase requests.
- Supports an explicitly confirmed buy mode for authenticated purchase attempts.
- Lets users configure marketplace polling speed and a separate delay between individual buy attempts.
- Applies a current-session spend cap before purchase requests are sent.
- Tracks session detections, successful purchases, silver spent, runtime, and lifetime local totals.
- Displays marketplace session state, saved credential state, monitor status, and recent events in one dashboard.
- Provides a marketplace wallet view for checking stored silver, Value Pack state, and marketplace weight data.

### Technical Features

- Reverse-engineered marketplace API integration across public listing endpoints, authenticated session endpoints, wallet data, and buy submission flow.
- Concurrent public category scanning for male/female outfit sections with isolated unauthenticated request state.
- Custom decoder for the marketplace's packed Huffman response format, including optimized byte-transition decoding for repeated polling.
- Cookie-based session persistence with migration away from legacy pickled session storage.
- Credential handling split between local email storage and OS keyring-backed password storage.
- Structured error handling around network timeouts, invalid JSON, unexpected API shapes, expired sessions, and known purchase result codes.
- Purchase accounting that parses `BuyItem` responses to distinguish immediate purchases from pre-order placement and records actual execution price.
- Long-running async task orchestration for polling, session refresh checks, monitor crash handling, and capped backoff after repeated failures.
- Textual terminal UI with live dashboard updates, modal-based controls, confirmation flows, and headless UI test coverage.
- Focused unit coverage for scan parsing, pricing conversion, spend caps, session refresh behavior, buy-result handling, runtime file initialization, and dashboard workflows.

## How It Works

The monitor checks the public outfit marketplace categories on a configurable polling window. It pulls the male and female outfit subcategories concurrently, decodes the packed marketplace response, and filters rows with available stock.

When running in watch-only mode, detections are written to the dashboard event log without making purchase requests. When buy mode is enabled, detections pass through outfit price rules, the current spend cap, and a configurable delay between individual buy attempts.

Authenticated requests use a saved marketplace cookie session when available. The app can refresh session validity, re-authenticate with saved credentials when needed, and record successful purchases using the actual price returned by the marketplace API.

## Project Status

This project is currently undergoing a codebase rewrite and Textual UI migration. Features may be incomplete, unstable, or temporarily broken while the modernization work is in progress.

## Supported Versions

Last verified compatibility: July 14, 2025.

Steam accounts and OTP-enabled accounts are not supported (yet). Only launcher accounts without OTP are supported.

## Running the App

Install dependencies from the repository root:

```powershell
py -3 -m pip install -r requirements.txt
```

On Windows, start the app with:

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

## Contact

For questions or bug reports, use the project issue tracker or the listed Discord contact: `._.__.__._._.__._____.__._.___.`

## Planned Work

- Steam account compatibility.
- More configurable marketplace categories.
