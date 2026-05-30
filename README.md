# Marketplace Tools

![Marketplace Tools dashboard](docs/assets/dashboard.png)


Python CLI app for monitoring the *Black Desert Online* marketplace. It maintains an authenticated marketplace session, and is able to execute buy orders remotely. It continuously check for outfit availability with a custom delay in the background, and purchase them upon detection, in milliseconds.


## Features

### Core Capabilities

- Live interactive dashboard.
- Monitors BDO marketplace for outfit listings.
- Automated purchasing of outfits upon detection.
- Adjustable marketplace polling speed and delay between individual buy attempts.
- Custom silver spend cap per session, stopping future purchases if cap is met.
- Tracks current session's outfit detections, successful purchases, and silver spent. 
- Tracks lifetime silver spent, and successful purchases.
- Provides logging for actions, purchases, detection, and errors.
- Provides a marketplace wallet view for checking stored silver, Value Pack state, and marketplace inventory data (WIP).

### Technical Features

- Marketplace API integration for listing scans, wallet data, session refresh, authentication, and `BuyItem` purchase requests.
- Concurrent marketplace polling with isolated unauthenticated `requests.Session` clients for male and female outfit categories, preserving connection reuse without sharing authenticated state.
- Custom Huffman response decoder for packed marketplace payloads, optimized for repeated high-frequency scans.
- Async monitor orchestration around blocking HTTP calls using `asyncio.to_thread()`, randomized polling windows, capped retry backoff, task lifecycle guards, and crash-aware monitor state.
- Secure session and credential persistence with JSON cookie storage, legacy pickle-session migration, local email initialization, and OS keyring-backed password storage.
- Safety-gated purchase pipeline with explicit buy-mode confirmation, spend-cap enforcement, configurable per-item buy delay, session-expiration recovery, and one-time retry on expired marketplace sessions.
- Structured purchase result parsing that separates fulfilled purchases from pre-order placements, records actual execution prices, and maps known marketplace result codes into actionable event-log messages.
- Resilient network and response validation for timeouts, malformed JSON, unexpected API shapes, invalid listing rows, stale pricing, duplicate orders, and unavailable items.
- Textual-based terminal dashboard with live runtime metrics, modal control flows, wallet/status views, test-mode-only simulation controls, and headless UI workflow tests.
- Focused unit coverage for listing parsing, pricing conversion, spend caps, session refresh behavior, purchase accounting, runtime file initialization, and dashboard workflows.

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

Known problematic result codes:

- `resultCode=30`: identical order already exists. This has been observed with `resultMsg=eErrNoAlreadyReservationDay`.
- `resultCode=34`: item unavailable, already taken, or the request would create a duplicate pre-order.
- `resultCode=-14`: price mismatch. This can happen when PA decide to change max outfit prices. needs updating if that's the case.
- `resultCode=2000`: marketplace login session expired upon buy attempt. The app attempts to refresh/re-authenticate and re buy the item.

Unknown purchase codes are reported as `resultCode {code}` in the event log so they can be documented after a new capture.

## Contact

For questions or bug reports, use the project issue tracker or the listed Discord contact: `._.__.__._._.__._____.__._.___.`

## Planned Work

- Steam account compatibility.
- More configurable marketplace categories.
