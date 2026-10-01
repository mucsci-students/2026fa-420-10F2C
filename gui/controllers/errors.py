"""
Shared error handling for GUI controllers (Sprint 2 Sections 4, 10, 19).

Controllers never build HTTP responses. When something goes wrong in an
expected way (validation failure, a rule the library does not enforce, a
missing configuration, a stale index), they raise ControllerError carrying one
or more FieldError items. Views turn those into messages on the form field
they belong to, or on the form as a whole -- so raw Pydantic text and
tracebacks never reach the user (Section 10).

Both places the scheduler library reports problems end up here:
  * a nested type failing on construction, e.g. TimeBlock(...), whose error
    locations are plain field names ("start", "end", "spacing");
  * app.crud.apply_edit() rejecting the whole CombinedConfig, whose error
    locations are full paths ("time_slot_config", "times", "MON").
apply_edit() chains the original Pydantic error as __cause__, so the
structured .errors() data is available without parsing text.

Every configuration area's controller should reuse this module; add new
friendly messages to _friendly_message() as new library error types show up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.crud import ReferenceError_, ValidationFailure
from app.session import ConfigError


@dataclass(frozen=True)
class FieldError:
    """One user-facing problem.

    `field` is a form field name, or None when the problem belongs to the
    form (or page) as a whole rather than a single input.
    """

    field: str | None
    message: str


class ControllerError(Exception):
    """An expected, user-correctable failure raised by a controller."""

    def __init__(self, errors: Iterable[FieldError] | str):
        if isinstance(errors, str):
            errors = [FieldError(None, errors)]
        self.errors: list[FieldError] = list(errors)
        super().__init__(" ".join(item.message for item in self.errors))

    @property
    def message(self) -> str:
        """All messages joined into one string (for flash messages/logs)."""
        return str(self)


def _friendly_message(error: dict) -> tuple[str, bool]:
    """Return (text, known). `known` is False when we fell back to the
    library's own wording, so the caller can add location context."""
    kind = error.get("type", "")
    location = [str(part) for part in error.get("loc", ())]
    last = location[-1] if location else ""
    context = error.get("ctx") or {}

    if kind == "time_block_end_not_after_start":
        return "End time must be later than the start time.", True
    if kind == "missing_weekday_time_blocks":
        return f"{last} needs at least one time block.", True
    if kind == "string_pattern_mismatch" and last in ("start", "end"):
        return "Enter a valid 24-hour time such as 09:00 or 17:30.", True
    if kind == "greater_than" and "gt" in context:
        return f"Enter a number greater than {context['gt']}.", True
    if kind == "missing":
        return "This field is required.", True
    return str(error.get("msg") or "Invalid value."), False


def translate_validation_error(exc: Exception, form_fields: Iterable[str] = ()) -> list[FieldError]:
    """Turn a library validation failure into FieldError items.

    `form_fields` lists the form field names errors may be attached to; an
    error whose last location part matches one is attached to that field,
    anything else becomes a form-level error.
    """
    form_fields = tuple(form_fields)
    source = exc
    if isinstance(exc, ValidationFailure) and exc.__cause__ is not None:
        source = exc.__cause__

    raw_errors = None
    errors_method = getattr(source, "errors", None)
    if callable(errors_method):
        try:
            raw_errors = list(errors_method())
        except Exception:  # pragma: no cover - defensive, fall back to text
            raw_errors = None

    if not raw_errors:
        text = exc.message if isinstance(exc, ValidationFailure) else str(exc)
        return [FieldError(None, text or "The change was rejected by validation.")]

    items: list[FieldError] = []
    for error in raw_errors:
        location = [str(part) for part in error.get("loc", ())]
        message, known = _friendly_message(error)
        target = location[-1] if location and location[-1] in form_fields else None
        if not known and target is None and location:
            message = f"{message} (at {'.'.join(location)})"
        items.append(FieldError(target, message))
    return items


def to_controller_error(exc: Exception, form_fields: Iterable[str] = ()) -> ControllerError:
    """Convert any exception the app/ layer raises into a ControllerError."""
    if isinstance(exc, ControllerError):
        return exc
    if isinstance(exc, (ReferenceError_, ConfigError)):
        return ControllerError(str(exc))
    return ControllerError(translate_validation_error(exc, form_fields))


def describe_problems(exc: Exception, limit: int | None = None) -> list[str]:
    """Plain-language problem list for a whole-configuration failure.

    Unlike translate_validation_error() (which attaches errors to form
    fields), every item here names WHERE the problem is, e.g.
    "This field is required. (at config > rooms > 0 > capacity)", because a
    loaded or saved configuration has no form to hang the errors on
    (Section 10: name the affected area). `limit` caps the list and adds
    an "...and N more" line, so a badly broken file stays readable.
    """
    source = exc
    if isinstance(exc, ValidationFailure) and exc.__cause__ is not None:
        source = exc.__cause__

    raw_errors = None
    errors_method = getattr(source, "errors", None)
    if callable(errors_method):
        try:
            raw_errors = list(errors_method())
        except Exception:  # pragma: no cover - defensive, fall back to text
            raw_errors = None

    if not raw_errors:
        text = str(exc).strip()[:300]
        return [text or "The configuration is not valid."]

    items: list[str] = []
    for error in raw_errors:
        location = [str(part) for part in error.get("loc", ())]
        message, _ = _friendly_message(error)
        items.append(f"{message} (at {' > '.join(location)})" if location else message)

    if limit is not None and len(items) > limit:
        extra = len(items) - limit
        items = items[:limit] + [f"...and {extra} more problem{'' if extra == 1 else 's'}."]
    return items
