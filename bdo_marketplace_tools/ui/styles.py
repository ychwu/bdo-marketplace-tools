from bdo_marketplace_tools.ui.display import COLOR_BRAND, COLOR_CAUTION, COLOR_ERROR, COLOR_TEXT_MUTED


APP_CSS = """
    Screen {
        background: #101010;
    }

    #shell {
        height: 1fr;
    }

    #topbar {
        dock: top;
        height: 2;
        background: #171717;
        border-bottom: solid __COLOR_BRAND__;
        padding: 0 2;
    }

    #brand {
        width: auto;
        color: __COLOR_BRAND__;
        text-style: bold;
        margin-right: 0;
        content-align: left middle;
    }

    #tabs {
        width: auto;
        height: 1;
    }

    .nav-tab {
        width: auto;
        height: 1;
        margin: 0 2;
        color: __COLOR_TEXT_MUTED__;
        content-align: center middle;
    }

    .nav-tab:hover {
        color: __COLOR_BRAND__;
    }

    .nav-tab-active {
        color: __COLOR_BRAND__;
        text-style: bold;
    }

    #tab-settings {
        width: 2;
        height: 1;
        margin: 0 5 0 1;
        color: __COLOR_TEXT_MUTED__;
        content-align: center middle;
    }

    #tab-settings:hover {
        color: __COLOR_BRAND__;
        background: #242424;
    }

    #tab-settings.nav-tab-active {
        color: __COLOR_BRAND__;
        background: #1e1e1e;
        text-style: bold;
    }

    #topbar-spacer {
        width: 1fr;
    }

    #header-session {
        width: auto;
        margin-left: 2;
        content-align: right middle;
    }

    #build-info {
        width: auto;
        margin-left: 2;
        color: __COLOR_TEXT_MUTED__;
        text-style: dim;
        content-align: right middle;
    }

    #main {
        height: 1fr;
        padding: 0 2;
    }

    #welcome-card {
        height: auto;
        border: round #3a3a3a;
        padding: 0 1;
        margin: 1 0;
    }

    #banner {
        height: 12;
        color: __COLOR_BRAND__;
        text-style: bold;
        content-align: center middle;
        overflow: hidden;
    }

    #welcome-footer {
        height: 2;
        color: __COLOR_TEXT_MUTED__;
        content-align: center middle;
        border-top: solid #2b2b2b;
    }

    #body {
        height: 1fr;
    }

    #test-controls {
        width: 26;
        min-width: 22;
        height: 1fr;
        margin-left: 1;
        overflow-y: auto;
    }

    #test-controls Button {
        width: 100%;
        min-width: 0;
        margin: 0;
        text-align: left;
        content-align: left middle;
    }

    #statusbar {
        dock: bottom;
        height: 1;
        background: #101010;
        padding: 0 1;
    }

    #status-keys {
        width: 1fr;
        color: __COLOR_TEXT_MUTED__;
        content-align: left middle;
    }

    #status-state {
        width: auto;
        color: __COLOR_TEXT_MUTED__;
        content-align: right middle;
    }

    .screen-heading {
        text-style: bold;
        color: __COLOR_BRAND__;
        margin-bottom: 1;
    }

    .panel {
        border: round #3a3a3a;
        padding: 1;
        margin-bottom: 1;
    }

    .settings-panel {
        border: round #3a3a3a;
        border-title-color: #d8d3c8;
        border-title-style: bold;
        padding: 1;
        margin-bottom: 1;
    }

    .settings-note {
        color: __COLOR_TEXT_MUTED__;
        margin-bottom: 1;
    }

    #settings-about {
        margin-bottom: 0;
    }

    #settings-cache-threshold-input {
        width: 8;
        height: 3;
        margin-right: 1;
        border: round #d8d3c8;
        background: transparent;
        color: #d8d3c8;
        padding: 0 1;
    }

    #settings-cache-threshold-input:focus {
        border: round #d8d3c8;
        background: transparent;
        color: #d8d3c8;
    }

    #settings-cache-threshold-input > .input--cursor {
        background: #d8d3c8;
        color: #111111;
    }

    #settings-cache-threshold-input > .input--placeholder {
        color: __COLOR_TEXT_MUTED__;
    }

    .row {
        height: auto;
        margin-bottom: 1;
    }

    .row > Label {
        width: 18;
        text-style: bold;
    }

    #dashboard-panel {
        height: auto;
        margin-bottom: 0;
    }

    #dashboard-tiles {
        height: 7;
    }

    .dashboard-tile-row {
        height: 3;
        padding-left: 1;
    }

    #dashboard-primary-tiles {
        margin-bottom: 1;
    }

    .dashboard-tile {
        width: 23;
        height: 3;
        min-width: 13;
        margin: 0 1 1 0;
        padding: 0 1;
        content-align: left middle;
    }

    .dashboard-tile-gap {
        width: 1fr;
        min-width: 2;
    }

    .tile-clickable {
        background: #262626;
        color: #d8d3c8;
    }

    .tile-clickable:hover {
        background: #333231;
    }

    .tile-clickable:focus {
        background: #333231;
    }

    .tile-muted {
        background: #151515;
        color: #777777;
    }

    #event-log {
        height: 1fr;
        min-height: 6;
        border: round #3a3a3a;
        border-title-color: #d8d3c8;
        border-title-style: bold;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
        scrollbar-color: #343434;
        scrollbar-color-hover: #4a4a4a;
        scrollbar-color-active: #5f5f5f;
        scrollbar-background: #111111;
        scrollbar-background-hover: #111111;
        scrollbar-background-active: #111111;
        scrollbar-corner-color: #111111;
    }

    #event-log-toolbar {
        height: 1;
        margin-top: 0;
        margin-bottom: 0;
        align-horizontal: right;
    }

    #log-filter-separator {
        width: auto;
        margin: 0 1;
        content-align: center middle;
        color: #777777;
    }

    .log-filter-option {
        width: auto;
        height: 1;
        content-align: center middle;
        color: __COLOR_TEXT_MUTED__;
        background: transparent;
    }

    .log-filter-option:hover {
        color: __COLOR_BRAND__;
    }

    .log-filter-selected {
        color: __COLOR_BRAND__;
        text-style: bold;
    }

    #stats-actions,
    #wallet-actions {
        height: auto;
        margin-bottom: 1;
    }

    .wip-note {
        border: round #3a3a3a;
        border-title-color: __COLOR_BRAND__;
        color: __COLOR_TEXT_MUTED__;
        padding: 0 1;
        margin: 1 0 1 0;
    }

    .modal-action-tile {
        width: 18;
        height: 3;
        margin-right: 1;
        content-align: center middle;
        border: round #d8d3c8;
        color: #d8d3c8;
        background: transparent;
    }

    .modal-action-tile:hover {
        border: round __COLOR_BRAND__;
        color: __COLOR_BRAND__;
        background: transparent;
    }

    .modal-action-destructive {
        border: round __COLOR_ERROR__;
        color: __COLOR_ERROR__;
    }

    .modal-action-destructive:hover {
        border: round __COLOR_ERROR__;
        color: #f2c0c0;
        background: transparent;
    }

    .action-card {
        height: auto;
        border: round #3a3a3a;
        border-title-color: #d8d3c8;
        border-title-style: bold;
        padding: 0 1;
        margin-bottom: 1;
    }

    #settings-update-card, #settings-storage-card {
        margin-bottom: 0;
    }

    .action-card-info {
        width: 1fr;
        height: 3;
        content-align: left middle;
    }

    .action-card-line {
        width: 1fr;
        height: 1;
        content-align: left middle;
        margin-bottom: 1;
    }

    .action-card-spacer {
        width: 1fr;
        height: 1;
    }

    #settings-storage-card, #settings-danger-card {
        padding: 1 1;
    }

    .danger-card {
        border: round __COLOR_ERROR__;
        border-title-color: __COLOR_ERROR__;
    }

    .cache-controls-row, .danger-actions-row {
        height: 3;
    }

    .cache-inline-label {
        width: auto;
        height: 3;
        content-align: center middle;
        color: __COLOR_TEXT_MUTED__;
        margin-right: 1;
    }

    .modal-action-compact {
        width: auto;
        min-width: 10;
        padding: 0 2;
    }

    .settings-section-title {
        color: __COLOR_BRAND__;
        text-style: bold;
        margin-bottom: 1;
    }

    #settings-status {
        color: __COLOR_TEXT_MUTED__;
        min-height: 1;
        margin-top: 0;
        margin-bottom: 1;
    }

    .stats-section-title {
        color: __COLOR_BRAND__;
        text-style: bold;
        margin-bottom: 1;
    }

    .stats-row {
        height: 4;
        margin-bottom: 1;
    }

    .stats-tile {
        width: 1fr;
        height: 4;
        min-width: 12;
        margin-right: 1;
        padding: 0 1;
        content-align: center middle;
        border: round #3a3a3a;
        border-title-color: #d8d3c8;
        border-title-style: bold;
        border-title-align: center;
    }

    #content {
        height: 1fr;
        overflow-y: auto;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
        scrollbar-color: #343434;
        scrollbar-color-hover: #4a4a4a;
        scrollbar-color-active: #5f5f5f;
        scrollbar-background: #101010;
        scrollbar-background-hover: #101010;
        scrollbar-background-active: #101010;
        scrollbar-corner-color: #101010;
    }

    Input, Select {
        width: 60;
    }

    Button {
        margin-right: 1;
    }
    """.replace("__COLOR_BRAND__", COLOR_BRAND).replace("__COLOR_TEXT_MUTED__", COLOR_TEXT_MUTED).replace("__COLOR_ERROR__", COLOR_ERROR).replace("__COLOR_CAUTION__", COLOR_CAUTION)


MODAL_CSS = """
    DashboardModalScreen,
    ConfirmBuyModeScreen,
    MonitorModal,
    SpendCapModal,
    PollingModal,
    CredentialsModal,
    PACredentialsModal,
    SessionModal,
    SessionRefreshConfirmScreen {
        align: center middle;
        background: #101010 72%;
    }

    .modal-card {
        width: 68;
        max-width: 90%;
        height: auto;
        border: round __COLOR_BRAND__;
        border-title-color: __COLOR_BRAND__;
        border-title-style: bold;
        background: #171717 96%;
        padding: 1 2;
    }

    .modal-heading {
        color: __COLOR_BRAND__;
        text-style: bold;
        margin-bottom: 1;
    }

    .modal-summary {
        border: round #3a3a3a;
        padding: 1;
        margin-bottom: 1;
    }

    .modal-note {
        color: #b8b2a8;
        margin-top: 1;
        margin-bottom: 1;
    }

    .modal-warning {
        color: #f0b45a;
        min-height: 1;
        margin-top: 1;
    }

    .modal-summary-row {
        height: 4;
        margin-bottom: 1;
    }

    .modal-section-title {
        color: __COLOR_BRAND__;
        text-style: bold;
        margin-top: 1;
        margin-bottom: 1;
    }

    .modal-info-tile {
        width: 1fr;
        min-width: 12;
        height: 4;
        margin-right: 1;
        padding: 0 1;
        content-align: center middle;
        border: round #d8d3c8;
        border-title-color: #d8d3c8;
        border-title-style: bold;
        border-title-align: center;
    }

    .modal-info-clickable:hover {
        border: round __COLOR_BRAND__;
        border-title-color: __COLOR_BRAND__;
        color: __COLOR_BRAND__;
    }

    .modal-info-muted {
        border: round #2b2b2b;
        border-title-color: #777777;
        color: #aaaaaa;
    }

    .preset-selected {
        border: round __COLOR_BRAND__;
        border-title-color: __COLOR_BRAND__;
        color: __COLOR_BRAND__;
    }

    .modal-info-wide {
        width: 2fr;
        min-width: 24;
    }

    .modal-row {
        height: auto;
        margin-bottom: 1;
        align: left middle;
    }

    .modal-row > Label {
        width: 18;
        text-style: bold;
        content-align: left middle;
    }

    .modal-actions {
        height: auto;
        margin-top: 1;
    }

    .modal-actions Button {
        border: round #d8d3c8;
        background: #171717;
        color: #d8d3c8;
        margin-right: 1;
    }

    .modal-actions Button:hover {
        border: round __COLOR_BRAND__;
        background: #171717;
        color: __COLOR_BRAND__;
    }

    .modal-actions Button:focus {
        border: round #d8d3c8;
        background: #171717;
        color: #d8d3c8;
    }

    .modal-actions Button:disabled,
    .modal-actions Button.-primary:disabled,
    .modal-actions Button.-warning:disabled,
    .modal-actions Button.-error:disabled {
        border: round #2b2b2b;
        border-title-color: #777777;
        background: #171717;
        color: #777777;
        text-opacity: 60%;
    }

    .modal-actions Button.-primary,
    .modal-actions Button.-warning,
    .modal-actions Button.-error {
        border: round #d8d3c8;
        background: #171717;
        color: #d8d3c8;
    }

    .modal-actions Button.-primary:hover,
    .modal-actions Button.-warning:hover,
    .modal-actions Button.-error:hover {
        border: round __COLOR_BRAND__;
        background: #171717;
        color: __COLOR_BRAND__;
    }

    .modal-actions Button.-primary:focus,
    .modal-actions Button.-warning:focus,
    .modal-actions Button.-error:focus {
        border: round #d8d3c8;
        background: #171717;
        color: #d8d3c8;
    }

    #clear-credentials {
        border: round __COLOR_ERROR__;
        color: __COLOR_ERROR__;
    }

    #clear-credentials:hover {
        border: round __COLOR_ERROR__;
        color: #f2c0c0;
    }

    #clear-credentials:focus {
        border: round __COLOR_ERROR__;
        color: __COLOR_ERROR__;
    }

    .modal-action-tile {
        width: 18;
        height: 3;
        margin-right: 1;
        content-align: center middle;
        border: round #d8d3c8;
        color: #d8d3c8;
        background: #171717;
    }

    .modal-action-tile:hover {
        border: round __COLOR_BRAND__;
        color: __COLOR_BRAND__;
        background: #171717;
    }

    .modal-card Input {
        border: round #d8d3c8;
        background: #171717;
        color: #d8d3c8;
        width: 1fr;
    }

    .modal-card Input:focus {
        border: round __COLOR_BRAND__;
        background: #171717;
        background-tint: transparent;
    }

    .modal-card Select > SelectCurrent {
        border: round #d8d3c8;
        background: #171717;
        color: #d8d3c8;
    }

    .modal-card Select:focus > SelectCurrent {
        border: round __COLOR_BRAND__;
        background: #171717;
        background-tint: transparent;
    }

    .modal-card Select > SelectOverlay {
        border: round #d8d3c8;
        background: #171717;
        color: #d8d3c8;
    }

    .modal-card Select > SelectOverlay > .option-list--option-highlighted {
        background: #f2efe7;
        color: #101010;
    }

    .modal-card Switch {
        border: round #d8d3c8;
        background: #171717;
        padding: 0 2;
    }

    .modal-card Switch:focus,
    .modal-card Switch:hover {
        border: round __COLOR_BRAND__;
        background: #171717;
        background-tint: transparent;
    }

    .modal-card Switch .switch--slider {
        background: #171717;
        color: #777777;
    }

    .modal-card Switch.-on .switch--slider {
        color: __COLOR_BRAND__;
    }
    """.replace("__COLOR_BRAND__", COLOR_BRAND).replace("__COLOR_ERROR__", COLOR_ERROR)