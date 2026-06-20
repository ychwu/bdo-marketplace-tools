"""Check GitHub for a newer published app version and report it (notify-only).

Source of truth: ``APP_VERSION`` in ``bdo_marketplace_tools/version.py`` on the repo's
default branch, read as a raw file. The release/versioning thread already bumps that
constant, so this check needs no extra release step (no tags or GitHub Releases required).

This module never downloads, installs, or runs anything. It only reads a remote version
string, compares it to the local one, and lets callers tell the user. Every public entry
point is exception-safe: a network or parse failure is reported as a soft error result,
never raised, so a failed check can be treated as a no-op.
"""

import re

import requests

from bdo_marketplace_tools.version import APP_VERSION


GITHUB_OWNER = "ychwu"
GITHUB_REPO = "bdo-marketplace-tools"
DEFAULT_BRANCH = "main"

REMOTE_VERSION_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/"
    f"{DEFAULT_BRANCH}/bdo_marketplace_tools/version.py"
)
RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"

UPDATE_CHECK_TIMEOUT = 8
_USER_AGENT = f"{GITHUB_REPO}/{APP_VERSION}"

# Pull APP_VERSION = "..." out of the raw version.py text.
_REMOTE_VERSION_PATTERN = re.compile(r"""^APP_VERSION\s*=\s*["']([^"']+)["']""", re.MULTILINE)
# Parse X[.Y[.Z]] with an optional -prerelease suffix (e.g. "1.1.0-beta", "0.2.0", "v1.2").
_VERSION_CORE_PATTERN = re.compile(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+.](.*))?\s*$")


class UpdateCheckResult:
    """Outcome of one update check.

    ``status`` is one of:
      - ``"update-available"``: ``latest_version`` is newer than ``current_version``.
      - ``"up-to-date"``: the remote version is the same or older.
      - ``"error"``: the remote version could not be fetched or parsed (``error`` set).
    """

    def __init__(self, status, current_version, latest_version=None, error=None):
        self.status = status
        self.current_version = current_version
        self.latest_version = latest_version
        self.error = error

    @property
    def update_available(self):
        return self.status == "update-available"

    def __repr__(self):  # pragma: no cover - debugging aid only
        return (
            f"UpdateCheckResult(status={self.status!r}, current={self.current_version!r}, "
            f"latest={self.latest_version!r}, error={self.error!r})"
        )


def parse_version(value):
    """Parse a version string into a comparable tuple, or ``None`` if unrecognizable.

    Returns ``((major, minor, patch), prerelease_rank, prerelease_label)`` where a release
    with no prerelease (rank ``1``) sorts above its own prerelease (rank ``0``) at the same
    numeric core, e.g. ``1.1.0`` > ``1.1.0-beta``.
    """
    if not isinstance(value, str):
        return None
    match = _VERSION_CORE_PATTERN.match(value)
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    prerelease = (match.group(4) or "").strip().lower()
    prerelease_rank = 0 if prerelease else 1
    return ((major, minor, patch), prerelease_rank, prerelease)


def is_newer_version(remote, local):
    """True only when ``remote`` is strictly newer than ``local``.

    Numeric core wins first; at an equal core a final release beats a prerelease; two
    prereleases at the same core fall back to a lexical label compare (best effort, good
    enough for alpha/beta/rc). Unparseable versions are treated as "not newer" so a bad
    remote string can never trigger a spurious update prompt.
    """
    remote_parsed = parse_version(remote)
    local_parsed = parse_version(local)
    if remote_parsed is None or local_parsed is None:
        return False

    remote_core, remote_rank, remote_pre = remote_parsed
    local_core, local_rank, local_pre = local_parsed
    if remote_core != local_core:
        return remote_core > local_core
    if remote_rank != local_rank:
        return remote_rank > local_rank
    return remote_pre > local_pre


def extract_remote_version(text):
    """Read ``APP_VERSION`` out of raw version.py text, or ``None`` if absent."""
    if not isinstance(text, str):
        return None
    match = _REMOTE_VERSION_PATTERN.search(text)
    return match.group(1) if match else None


def fetch_remote_version_text(url=REMOTE_VERSION_URL, timeout=UPDATE_CHECK_TIMEOUT):
    """Fetch the raw remote version.py text. Raises on network/HTTP error."""
    response = requests.get(url, timeout=timeout, headers={"User-Agent": _USER_AGENT})
    response.raise_for_status()
    return response.text


def check_for_update(current_version=APP_VERSION, *, fetcher=fetch_remote_version_text):
    """Run one exception-safe update check and return an :class:`UpdateCheckResult`.

    ``fetcher`` is injectable so tests can supply a fake without touching the network. This
    call is synchronous; async callers should wrap it in ``asyncio.to_thread``.
    """
    try:
        text = fetcher()
    except Exception as exc:  # noqa: BLE001 - any network/IO failure is a soft no-op
        return UpdateCheckResult("error", current_version, error=str(exc))

    latest = extract_remote_version(text)
    if not latest:
        return UpdateCheckResult("error", current_version, error="Remote version not found.")

    if is_newer_version(latest, current_version):
        return UpdateCheckResult("update-available", current_version, latest_version=latest)
    return UpdateCheckResult("up-to-date", current_version, latest_version=latest)
