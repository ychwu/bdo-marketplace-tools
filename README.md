# Marketplace Tools

![Python](https://img.shields.io/badge/Python-3.x-blue)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6)
![UI](https://img.shields.io/badge/UI-Textual-orange)
![Default Mode](https://img.shields.io/badge/Default-Watch--Only-green)
![Status](https://img.shields.io/badge/Status-Rewrite%20In%20Progress-yellow)

![Marketplace Tools dashboard](docs/assets/dashboard.png)


Python CLI app for monitoring the *Black Desert Online* marketplace through authenticated HTTP/API requests. It maintains a persistent marketplace session, continuously checks for outfit listings at a custom polling interval, handles long-running monitoring sessions with custom built re-authentication workflow, and executes buy-order requests as soon as matching items become available, in millieseconds.


## Features

### Core Capabilities

- Live interactive dashboard.
- Monitors BDO marketplace for outfit listings.
- Automated purchasing of outfits upon detection.
- Adjustable marketplace polling speed and delay between individual buy attempts.
- Custom silver spend cap per session, stopping future purchases if cap is met.
- Tracks current session's outfit detections, successful purchases, and silver spent. 
- Tracks lifetime silver spent, and successful purchases.
- Provides dashboard event logs with separate Core and UI views for technical monitor/session events versus interface confirmations.
- Allows saved marketplace session cookies to be cleared from App Settings for a fresh login/session.
- Remembers applied UI choices such as login method, polling speed, buy delay, spend cap, watch/buy mode, and event-log view across restarts.
- Provides a Marketplace Inventory WIP view for checking stored silver, Value Pack state, and marketplace inventory data.

### Technical Features

- Marketplace API integration for listing scans, wallet data, session refresh, authentication, and `BuyItem` purchase requests.
- Professional package layout under `bdo_marketplace_tools`, with market API logic, services, storage, and Textual UI separated into dedicated modules.
- Steam Account browser-session support through a visible Patchright Chrome login, cookie import into the existing marketplace session, and current-run gated automatic Steam re-authentication after the first validated refresh.
- Concurrent marketplace polling with isolated unauthenticated `requests.Session` clients for male and female outfit categories, preserving connection reuse without sharing authenticated state.
- Custom Huffman response decoder for packed marketplace payloads, optimized for repeated high-frequency scans.
- Async monitor orchestration around blocking HTTP calls using `asyncio.to_thread()`, randomized polling windows, capped retry backoff, task lifecycle guards, and crash-aware monitor state.
- Secure session and credential persistence under ignored `data/` runtime files, with versioned app settings, JSON cookie storage, fresh-start defaults, startup validation only for sessions last known valid, and OS keyring-backed password storage.
- Manual session-reset workflow that clears only marketplace cookies while preserving saved credentials.
- Safety-gated purchase pipeline with explicit buy-mode confirmation, spend-cap enforcement, configurable per-item buy delay, session-expiration recovery, and one-time retry on expired marketplace sessions.
- Structured purchase result parsing that separates fulfilled purchases from pre-order placements, records actual execution prices, and maps known marketplace result codes into actionable event-log messages.
- Resilient network and response validation for timeouts, malformed JSON, unexpected API shapes, invalid listing rows, stale pricing, duplicate orders, and unavailable items.
- Textual-based terminal dashboard with live runtime metrics, modal control flows, wallet/status views, test-mode-only simulation controls, and headless UI workflow tests.
- Focused unit coverage for listing parsing, pricing conversion, spend caps, session refresh behavior, purchase accounting, runtime file initialization, and dashboard workflows.

## Project Status

This project is currently undergoing a codebase rewrite and Textual UI migration. Features may be incomplete, unstable, or temporarily broken while the modernization work is in progress.

## Versioning

App/version metadata lives in `bdo_marketplace_tools/version.py` and is copied into `data/app_settings.json` under the `version` block whenever settings are read or saved. The same settings file stores non-secret app preferences such as login method, saved email, Steam setup state, saved-session last-known-valid state, polling, buy delay, spend cap, watch/buy mode, and event-log view. The UI App Settings screen shows the app version, release channel, and settings schema version for troubleshooting.

Versioning rule:

- Bump `APP_VERSION` for user-facing behavior, API/session handling, purchase flow, storage, or troubleshooting changes.
- Bump `SETTINGS_SCHEMA_VERSION` only when the shape or meaning of `data/app_settings.json` changes.
- Update `agent/CHANGELOG.md` for every behavior, API, storage, auth/session, or UI workflow change.
- Update README or local API docs when the change affects users, setup, endpoint behavior, auth flow, runtime files, or troubleshooting.
- Never include cookies, passwords, request tokens, or raw sensitive session data in version notes.

## Supported Versions

Last verified compatibility: July 14, 2025.

Pearl Abyss launcher accounts are supported through saved email/password credentials.
Steam accounts are supported through a visible browser session: choose `Steam Account` in the Credentials dashboard modal, complete Steam Initial Setup once, then use `Refresh Session` from the dashboard. Startup checks saved Steam sessions only after the saved cookies were previously validated; expired or unknown sessions require a manual browser refresh first. After one successful validated Steam refresh in the current app run, later refreshes can automatically click the normal PA/Steam continuation buttons when available. Steam mode does not use saved email/password credentials. OTP pages may be completed manually in that browser; the app does not store OTP values or submit OTP silently.

## Running the App

Install dependencies from the repository root:

```powershell
py -3 -m pip install -r requirements.txt
```

Steam browser-session mode uses Patchright with an installed Google Chrome browser.

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

This repository is provided as a proof of concept for authenticated web sessions, HTTP requests, and marketplace-style API integration. Use it only in environments where automation is permitted by the relevant terms of service. The project does not automate CAPTCHA challenges or other access-control interruptions.

## Known Issues

If your IP reputation is low, the official login flow may present a CAPTCHA. This project does not automate CAPTCHA challenges. Steam browser-session mode leaves the official browser visible so you can complete supported manual prompts yourself.

Known problematic result codes:

- `resultCode=30`: identical order already exists. This has been observed with `resultMsg=eErrNoAlreadyReservationDay`.
- `resultCode=34`: item unavailable, already taken, or the request would create a duplicate pre-order.
- `resultCode=-14`: price mismatch. This can happen when PA decide to change max outfit prices. needs updating if that's the case.
- `resultCode=2000`: marketplace login session expired upon buy attempt. The app attempts to refresh/re-authenticate and re buy the item.

Unknown purchase codes are reported as `resultCode {code}` in the event log so they can be documented after a new capture.

## Contact

For questions or bug reports, use the project issue tracker or the listed Discord contact: `._.__.__._._.__._____.__._.___.`

## Planned Work

- Manual QA for fresh and existing Steam browser profiles.
- More configurable marketplace categories.
