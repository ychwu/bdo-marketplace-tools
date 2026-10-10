import asyncio
import argparse
import os
import sys

import colorama

from bdo_marketplace_tools.market.api_handler import APIHandler
from bdo_marketplace_tools.services.purchase_executor import ApiPurchaseExecutor
from bdo_marketplace_tools.services.runtime import runtime_for_test_mode
from bdo_marketplace_tools.services.session_recovery import NoSessionFaults
from bdo_marketplace_tools.services.task_manager import BackgroundTasks
from bdo_marketplace_tools.services.diagnostics import DiagnosticRecorder
from bdo_marketplace_tools.storage.paths import DATA_DIR
from bdo_marketplace_tools.ui.app import MarketplaceToolsApp


TEST_MODE_ENV = "BDO_MARKET_TEST_MODE"
TRUE_VALUES = {"1", "true", "yes", "on"}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Launch Marketplace Tools.")
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Enable isolated developer tools and skip the startup session check.",
    )
    return parser.parse_args(argv)


def env_test_mode():
    return os.getenv(TEST_MODE_ENV, "").strip().lower() in TRUE_VALUES


async def run_app(test_mode=False, *, diagnostics=None):
    colorama.init()
    runtime = runtime_for_test_mode(test_mode)
    API = APIHandler(diagnostics=diagnostics)
    session_faults = NoSessionFaults()
    purchase_executor = ApiPurchaseExecutor(API)
    devtools = None

    if runtime.developer_tools_enabled:
        # Developer-only modules are deliberately absent from the normal startup path.
        from bdo_marketplace_tools.devtools import (
            DeveloperSessionFaults,
            DeveloperTools,
            SwitchablePurchaseExecutor,
        )

        session_faults = DeveloperSessionFaults()
        purchase_executor = SwitchablePurchaseExecutor(purchase_executor)

    task_manager = BackgroundTasks(
        API,
        runtime=runtime,
        session_faults=session_faults,
        purchase_executor=purchase_executor,
    )
    if runtime.developer_tools_enabled:
        devtools = DeveloperTools(task_manager, API, session_faults, purchase_executor)

    try:
        if not runtime.run_startup_session_check:
            API.login_status = False
            task_manager.add_event("Test mode active: startup session check skipped.", "warning")
        else:
            await task_manager.initial_login_check()

        app = MarketplaceToolsApp(task_manager, API, devtools=devtools)
        await app.run_async()
    finally:
        if devtools is not None:
            await devtools.shutdown()
        await task_manager.stop_pa_browser_worker_best_effort(
            "App shutdown could not finish Pearl Abyss Chrome worker cleanup"
        )


async def main(argv=None):
    args = parse_args(argv)
    test_mode = args.test_mode or env_test_mode()
    diagnostics = DiagnosticRecorder(DATA_DIR / ("diagnostics.test" if test_mode else "diagnostics"))
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()

    def handle_async_error(event_loop, context):
        diagnostics.record(context.get("message", "Unhandled asynchronous error"), exception=context.get("exception"))
        if previous_handler is not None:
            previous_handler(event_loop, context)
        else:
            event_loop.default_exception_handler(context)

    loop.set_exception_handler(handle_async_error)
    try:
        await run_app(test_mode=test_mode, diagnostics=diagnostics)
    except Exception as exc:
        path = diagnostics.record("Application failed", exception=exc)
        print(f"Diagnostic file: {path}" if path else f"Diagnostic save failed: {diagnostics.last_failure}", file=sys.stderr)
        raise
    finally:
        loop.set_exception_handler(previous_handler)


if __name__ == "__main__":
    asyncio.run(main())
