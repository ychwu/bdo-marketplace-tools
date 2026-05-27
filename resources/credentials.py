import json
from pathlib import Path

try:
    import keyring
    from keyring.errors import KeyringError
except ImportError:  # pragma: no cover - exercised only when dependency is missing
    keyring = None

    class KeyringError(Exception):
        pass


SERVICE_NAME = "BDO-OutfitBot"
INFO_PATH = Path(__file__).with_name("info.json")


class CredentialStoreError(RuntimeError):
    pass


def _read_info():
    try:
        with INFO_PATH.open("r", encoding="utf-8-sig") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise CredentialStoreError("credentials file is invalid JSON") from exc


def _write_info(data):
    INFO_PATH.parent.mkdir(parents=True, exist_ok=True)
    with INFO_PATH.open("w", encoding="utf-8") as file:
        json.dump(data, file)


def load_credentials():
    data = _read_info()
    email = data.get("email")
    legacy_password = data.get("password")

    if not email:
        return None, None

    if keyring is None:
        if legacy_password:
            _write_info({"email": email})
        raise CredentialStoreError("install the keyring package to load passwords securely")

    try:
        password = keyring.get_password(SERVICE_NAME, email)
        if legacy_password and not password:
            keyring.set_password(SERVICE_NAME, email, legacy_password)
            password = legacy_password
    except KeyringError as exc:
        raise CredentialStoreError("OS keyring is unavailable") from exc

    if legacy_password:
        _write_info({"email": email})

    return email, password


def save_credentials(email, password=None):
    if not email:
        raise CredentialStoreError("email is required before saving credentials")

    _write_info({"email": email})

    if password is None:
        return

    if keyring is None:
        raise CredentialStoreError("install the keyring package to save passwords securely")

    try:
        keyring.set_password(SERVICE_NAME, email, password)
    except KeyringError as exc:
        raise CredentialStoreError("OS keyring is unavailable") from exc
