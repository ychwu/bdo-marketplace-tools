"""One-time migration of pre-AppData data into the per-user data directory.

Older builds stored stats/settings/session/browser profiles inside the app folder
(`<repo>/data`). Data now lives in a per-user location (see `storage/paths.py`) so it
survives updates that replace the app folder. On first run after that change this copies the
old folder into the new location, leaving the original in place as a backup.

The copy is best-effort and never raises: if it fails, the app simply starts with fresh
defaults rather than refusing to launch.
"""

import shutil

from bdo_marketplace_tools.storage.paths import DATA_DIR, LEGACY_DATA_DIR


# Items copied from the legacy data folder. Covers every runtime file/dir paths.py defines.
MIGRATABLE_ENTRIES = (
    "app_settings.json",
    "session.json",
    "local_stats.json",
    "browser_profiles",
)


def _has_any_entry(directory):
    return any((directory / name).exists() for name in MIGRATABLE_ENTRIES)


def migrate_legacy_data_dir(legacy_dir=LEGACY_DATA_DIR, data_dir=DATA_DIR):
    """Copy legacy app-folder data into the per-user data dir if it hasn't been done yet.

    Returns True only when data was actually migrated. No-ops (returns False) when the
    legacy folder is missing/empty, when the new location already holds data, or when both
    paths resolve to the same place (portable / BDO_DATA_DIR pointing back at the repo).
    """
    try:
        if legacy_dir.resolve() == data_dir.resolve():
            return False
        if not legacy_dir.is_dir() or not _has_any_entry(legacy_dir):
            return False
        # Never clobber an existing per-user data set.
        if data_dir.exists() and _has_any_entry(data_dir):
            return False

        data_dir.mkdir(parents=True, exist_ok=True)
        for name in MIGRATABLE_ENTRIES:
            source = legacy_dir / name
            if not source.exists():
                continue
            destination = data_dir / name
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(source, destination)
        return True
    except OSError:
        return False
