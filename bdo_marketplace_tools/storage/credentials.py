from bdo_marketplace_tools.storage.app_settings import clear_saved_email, load_saved_email, save_saved_email

try:
    import keyring
    from keyring.errors import KeyringError, PasswordDeleteError
except ImportError:  # pragma: no cover - exercised only when dependency is missing
    keyring = None

    class KeyringError(Exception):
        pass

    class PasswordDeleteError(Exception):
        pass


SERVICE_NAME = "bdo-marketplace-tools"


class CredentialStoreError(RuntimeError):
    pass


def load_credentials():
    email = load_saved_email()
    if not email:
        return None, None

    if keyring is None:
        return email, None

    try:
        password = keyring.get_password(SERVICE_NAME, email)
    except KeyringError as exc:
        raise CredentialStoreError("OS keyring is unavailable") from exc

    return email, password


def save_credentials(email, password=None):
    if not email:
        raise CredentialStoreError("email is required before saving credentials")

    email = save_saved_email(email)
    if password is None:
        return

    if keyring is None:
        raise CredentialStoreError("install the keyring package to save passwords securely")

    try:
        keyring.set_password(SERVICE_NAME, email, password)
    except KeyringError as exc:
        raise CredentialStoreError("OS keyring is unavailable") from exc


def clear_credentials():
    email = load_saved_email()

    if email and keyring is not None:
        try:
            keyring.delete_password(SERVICE_NAME, email)
        except PasswordDeleteError:
            pass
        except KeyringError as exc:
            raise CredentialStoreError("OS keyring is unavailable") from exc

    clear_saved_email()
