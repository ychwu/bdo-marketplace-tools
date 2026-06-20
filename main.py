import asyncio
import argparse
import os

import colorama

from bdo_marketplace_tools.market.api_handler import APIHandler
from bdo_marketplace_tools.services.task_manager import BackgroundTasks
from bdo_marketplace_tools.storage.migration import migrate_legacy_data_dir
from bdo_marketplace_tools.ui.app import MarketplaceToolsApp


TEST_MODE_ENV = "BDO_MARKET_TEST_MODE"
TRUE_VALUES = {"1", "true", "yes", "on"}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Launch Marketplace Tools.")
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Skip the startup session check while working on UI or local behavior.",
    )
    return parser.parse_args(argv)


def env_test_mode():
    return os.getenv(TEST_MODE_ENV, "").strip().lower() in TRUE_VALUES


async def run_app(test_mode=False):
    colorama.init()
    # Move any pre-AppData data folder into the per-user data dir before anything reads it.
    data_migrated = migrate_legacy_data_dir()
    API = APIHandler()
    task_manager = BackgroundTasks(API, test_mode_enabled=test_mode)
    launch_mode = "test" if test_mode else "live"
    if data_migrated:
        task_manager.add_event(
            "Existing data moved to your user data folder; the old copy was kept as a backup.",
            "info",
        )

    if test_mode:
        API.login_status = False
        task_manager.add_event("Test mode active: startup session check skipped.", "warning")
    else:
        await task_manager.initial_login_check()

    app = MarketplaceToolsApp(task_manager, API, launch_mode=launch_mode)
    await app.run_async()


async def main(argv=None):
    args = parse_args(argv)
    await run_app(test_mode=args.test_mode or env_test_mode())


if __name__ == "__main__":
    asyncio.run(main())
