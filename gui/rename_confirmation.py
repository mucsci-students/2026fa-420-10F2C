"""Signed payload helpers for rename confirmation pages.

The first submit validates a rename but changes nothing. Its cleaned form data
is signed before the confirmation page is shown, so the second submit can only
apply the reviewed proposal rather than untrusted browser-supplied fields.
"""

from django.core import signing

RENAME_CONFIRMATION_SALT = "gui.rename_confirmation"
RENAME_CONFIRMATION_MAX_AGE_SECONDS = 300


class RenameConfirmationError(ValueError):
    """Raised when a signed confirmation cannot safely be used."""


def create_rename_confirmation(resource_key: str, identifier: str | int, form_data: dict) -> str:
    """Return a short-lived token for one reviewed resource rename."""
    return signing.dumps(
        {
            "resource_key": resource_key,
            "identifier": str(identifier),
            "form_data": form_data,
        },
        salt=RENAME_CONFIRMATION_SALT,
    )


def load_rename_confirmation(token: str, resource_key: str, identifier: str | int) -> dict:
    """Return reviewed form data only when its resource and URL still match."""
    try:
        payload = signing.loads(
            token,
            salt=RENAME_CONFIRMATION_SALT,
            max_age=RENAME_CONFIRMATION_MAX_AGE_SECONDS,
        )
    except signing.BadSignature as error:
        raise RenameConfirmationError("That rename confirmation is invalid or expired. Submit the edit again.") from error

    if not isinstance(payload, dict):
        raise RenameConfirmationError("That rename confirmation is invalid. Submit the edit again.")
    if payload.get("resource_key") != resource_key or payload.get("identifier") != str(identifier):
        raise RenameConfirmationError("That rename confirmation does not match this item. Submit the edit again.")
    form_data = payload.get("form_data")
    if not isinstance(form_data, dict):
        raise RenameConfirmationError("That rename confirmation is invalid. Submit the edit again.")
    return form_data