# Changelog

All notable released changes for `bdo-marketplace-tools` are documented here.

This file is updated by the dedicated release/versioning pass. Ordinary implementation
threads should add an ignored pending changeset under `.changesets/` instead of bumping
`APP_VERSION` or editing released sections directly.

## Unreleased

Pending changes are collected from ignored `.changesets/` files during a release pass.

## 0.1.15-beta - 2026-06-04

### Added

- Added Steam Account browser-session authentication as a second session acquisition path, using a visible app-owned Patchright Chrome profile, manual Steam/Pearl Abyss login, Central Market cookie capture, `/Home/AppSessionRefresh` validation, and existing session persistence.
- Added Steam Initial Setup from the Credentials modal so the persistent browser profile can visit the main Black Desert site, accept required-only cookie consent when available, save setup state, and close automatically on successful setup.
- Added current-run gated Steam automatic re-authentication after a validated manual Steam refresh, including visible auto-click support for the Pearl Abyss `Log in with Steam` button and Steam OpenID `Sign In` button.
- Added test-mode Steam controls for toggling automatic reauth, expiring the current session without stopping the monitor, and running the same reauth path used after an expired buy response.
- Added persistent UI preferences in `data/app_settings.json` for polling range, buy delay, spend cap, watch/buy mode, and the selected event-log view.
- Added a saved-session last-known-valid flag so startup only calls the session-refresh endpoint when saved cookies were previously validated and a cookie jar exists.
- Added separate Core and UI dashboard event-log streams, each with its own rolling 20-entry history, while retaining the combined compatibility stream.
- Added package-level runtime/version metadata and App Settings display for app version, release channel, settings schema, launch mode, and session-control summaries.

### Changed

- Reworked the project into the `bdo_marketplace_tools` package layout with separated market, services, storage, and UI modules, and moved private runtime state under ignored `data/` paths.
- Split the Textual UI into app, modal, widget, theme, and display modules, with dashboard actions centered around modal workflows instead of sidebar action buttons.
- Reworked the dashboard into compact workflow tiles for Monitor/Session, Spent/Credentials, Polling/Buy Delay, plus read-only Success Rate and Runtime tiles.
- Reworked dashboard tile states with semantic colors, status dots, centered tile content, dimmed read-only tiles, hover/focus states for interactive tiles, and a percentage color spectrum for Success Rate.
- Moved account/session mode selection into the Credentials modal and renamed login modes to `Pearl Abyss Account` and `Steam Account`.
- Reworked the Credentials modal into a login-method hub: Pearl Abyss mode opens a child email/password modal with inline validation, Steam mode uses the Steam Initial Setup tile, and switching modes preserves saved PA credentials.
- Changed Credentials dashboard/status presentation so saved PA credentials show as `PA Account` in gold, Steam shows in Steam blue, and Clear PA Account uses red destructive styling only in PA mode.
- Reworked the Session modal so the Session dashboard tile opens a modal first, Refresh Session asks for confirmation, PA mode shows a credentials guard without duplicating the account email, Steam mode shows Initial Setup status, and the refresh button no longer opens pre-highlighted.
- Standardized the dashboard Session tile description to `Authenticated` when online and `Refresh required` when offline for both Pearl Abyss and Steam login modes.
- Changed account-mode switching, credential changes, and manual session clears to stop or queue monitor shutdown, clear old marketplace cookies, mark the session offline, and reset Steam auto-reauth state.
- Changed Steam auth to be cookie-authoritative: browser cookie polling is local, Central Market cookies are captured as soon as the OAuth callback or market return has usable cookies, and final success remains server validation through `/Home/AppSessionRefresh`.
- Changed Steam-mode expired sessions to prompt browser refresh or run visible browser reauth instead of attempting Pearl Abyss email/password relogin.
- Changed buy-time expired-session handling so Steam mode runs the shared browser refresh flow and retries the same purchase batch once after validation succeeds.
- Changed startup session behavior to skip unnecessary session-refresh API calls when no known-valid saved session exists.
- Changed polling, buy-delay, and spend-cap modal inputs back to preview-only behavior until Save; invalid values keep the modal open and preserve the last saved setting.
- Reworked the Polling modal to explain scan frequency, remove the dropdown, show Fast/Balanced/Slow preset tiles, auto-fill custom min/max inputs from presets, and auto-highlight preset-equivalent custom ranges.
- Reworked the Buy Delay modal and buy-mode confirmations so users can configure and review the delay between purchase attempts separately from polling frequency.
- Renamed the Marketplace Wallet screen to Marketplace Inventory and kept it as a WIP inventory/silver/Value Pack diagnostic view.
- Reworked Stats, Marketplace Inventory, and App Settings utility actions to use the same rounded action-tile style while removing filled rectangular backgrounds from page-level actions.
- Reworked App Settings into app metadata and Session Debug sections with a clear saved-session action that preserves credentials.
- Replaced Textual's default header/menu with a custom title/clock header, removed the default top-left menu and clock expansion behavior, removed beta labels from the title/brand, and moved the exact build label to the lower-left sidebar.
- Reworked the dashboard event log with a compact Core/UI selector, neutral event-log title, separate rolling 20-entry streams, and a slimmer dark scrollbar instead of Textual's default blue scrollbar.
- Updated `run.bat` to launch through Windows Terminal at a usable size when available, forward arguments, avoid pycache churn, and close cleanly on successful app exits.

### Fixed

- Fixed Steam browser-session capture failures caused by waiting for later market UI page stability instead of validating once usable Central Market cookies existed.
- Fixed Steam browser flows staying open after successful cookie capture by closing the visible browser after setup or session validation succeeds.
- Fixed mode hot-swapping so purchases are not made with stale cookies from the previous account mode; if a purchase chain is already active, reset is deferred until the chain finishes.
- Fixed startup state discrepancies where the UI could show Pearl Abyss mode while a saved Steam session was active by persisting and restoring the selected account mode.
- Fixed event-log over-noise by routing interface confirmations to the UI stream and keeping Core focused on monitor, session, API, detection, purchase, and critical failure outcomes.
- Fixed dashboard/sidebar readability issues while iterating on the compact Textual layout and modernized modal styling.
- Fixed monitor controls so Start is disabled while already running, Stop is disabled while already stopped, repeated starts do not create duplicate tasks, and successful start flows close modal stacks back to the dashboard.
- Fixed several Textual focus artifacts where modal buttons appeared pre-highlighted after opening or clicking.
- Fixed missing-credential session refresh attempts so they stay in UI status instead of producing backend event-log warnings.

### Docs

- Added and refreshed local agent documentation for Steam auth, API behavior, runtime files, technical priorities, startup session checks, event-log categories, and the new versioning/changelog workflow.
- Replaced the old active agent changelog flow with the tracked root `CHANGELOG.md` plus ignored `.changesets/` files for future pending implementation notes.
- Froze the detailed pre-release modernization history in `agent/LEGACY_CHANGELOG.md`.

### Tests

- Added focused tests for Steam mode branching, browser-cookie import validation, failed import rollback, Steam auto-reauth branching, OTP status-only handling, missing-button manual-attention status, startup auto-gate behavior, and purchase-expiry retry behavior.
- Added tests for app-settings persistence, saved-session startup gating, event-log Core/UI separation, event-log view persistence, 20-entry event buffers, and fresh `BackgroundTasks` instances restoring saved UI state.
- Added and updated Textual workflow tests for credentials, session refresh, modal saves, buy-mode blocking/confirmation, test-mode reauth controls, Inventory navigation, and App Settings behavior.

## 0.1.0-beta - 2026-06-04

### Added

- Established the Textual dashboard app for marketplace monitoring, session management, wallet/status views, settings, stats, and test-mode tools.
- Added marketplace API integration for outfit stock scans, session refresh, wallet data, and guarded `BuyItem` purchase requests.
- Added Steam browser-session support through a visible Patchright Chrome profile and Pearl Abyss credential support through OS keyring-backed password storage.
- Added structured local runtime storage under ignored `data/` files for app settings, session cookies, local stats, and browser profiles.
- Added the `bdo_marketplace_tools` package layout with separated market, service, storage, and UI modules.
- Added app/version metadata in `bdo_marketplace_tools/version.py` and mirrored it into `data/app_settings.json` for troubleshooting.

### Changed

- Replaced the old scattered runtime/module layout with a fresh-start `data/` runtime model and direct `bdo_marketplace_tools.*` imports.
- Kept the detailed pre-release modernization history archived in deprecated `agent/LEGACY_CHANGELOG.md` as a local legacy record.
