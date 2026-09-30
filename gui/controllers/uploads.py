"""
Shared handling for files uploaded through a form (Sections 8, 17).

Any controller that accepts a file -- schedule import today, configuration
load next -- calls read_upload() first. It turns the usual problems (no
file, unreadable, empty, too large) into a ControllerError attached to the
form's file field, so every upload reports them the same way. What the
bytes MEAN (a schedule file, a configuration) is up to the caller.
"""

from __future__ import annotations

from gui.controllers.errors import ControllerError, FieldError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # configs and schedule sets are a few hundred KB


def read_upload(uploaded_file, field: str, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
    """Return the uploaded file's bytes, or raise ControllerError on `field`.

    `uploaded_file` is what a Django form's FileField gives you
    (form.cleaned_data[field]), or any object with .read().
    """
    if uploaded_file is None:
        raise ControllerError([FieldError(field, "Choose a file to load.")])

    size = getattr(uploaded_file, "size", None)
    if size is not None and size > max_bytes:
        raise ControllerError([FieldError(field, _too_large(size, max_bytes))])

    try:
        raw = uploaded_file.read()
    except OSError as error:
        raise ControllerError(
            [FieldError(field, "The file could not be read. Check the file and try again.")]
        ) from error

    if not raw or not raw.strip():
        raise ControllerError([FieldError(field, "The file is empty.")])
    if len(raw) > max_bytes:
        raise ControllerError([FieldError(field, _too_large(len(raw), max_bytes))])
    return raw


def _too_large(size: int, max_bytes: int) -> str:
    return (
        f"The file is too large ({size // 1024} KB). "
        f"Files over {max_bytes // (1024 * 1024)} MB are not supported."
    )
