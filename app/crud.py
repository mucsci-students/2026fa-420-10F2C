# ----------------------------------------------------------------------------------------------------------------------- #
#   app/crud.py                                                                                                           #
#                                                                                                                         #
#   Backbone piece #2: every add/modify/delete across every entity type            #
#   (faculty, course, room, lab, timeslot, pattern, meeting, global settings)      #
#   needs the SAME shape: mutate, validate the whole config, and roll back        #
#   to the previous state on failure -- without losing the user's typed          #
#   input or crashing the shell.                                                                                         #
#                                                                                                                         #
#   The scheduler library already provides this via CombinedConfig.edit_mode()    #
#   -- confirmed via `help(CombinedConfig.edit_mode)`:                            #
#                                                                                 #
#     "Returns: A context manager that yields a deep, independently editable      #
#      copy of this model... When the context exits normally, the copy is        #
#      reconstructed through the concrete model class to run all Pydantic        #
#      validation. Only a successfully validated state is copied back to the     #
#      original object."                                                        #
#                                                                                 #
#   CRITICAL: edit_mode() yields a COPY, not self. You must mutate the yielded    #
#   object (`with config.edit_mode() as draft:` ... `mutate_fn(draft)`), NOT      #
#   the original `config`. Mutating `config` directly inside the `with` block    #
#   appears to work (no error, changes visible immediately) but gets silently    #
#   discarded when the untouched, re-validated draft is copied back over your    #
#   original on exit. This bit us for real: `faculty add` printed "Faculty       #
#   added." with no error, but the new record was gone by the next command.      #
#                                                                                 #
#   Satisfies:                                                                                                          #
#     Req #6 (validate the COMPLETE configuration, not just one field)            #
#     Req #4 / Req #6 (previous valid in-memory config stays intact on failure)   #
#     Req #7 (deletion needs a place to plug in a reference check before the      #
#             mutation runs -- see check_no_references below)                     #
# ----------------------------------------------------------------------------------------------------------------------- #

from __future__ import annotations

from typing import Callable, Iterable

from scheduler.config import ValidationError


class ValidationFailure(Exception):
    """Raised when a mutation fails whole-config validation. Carries which
    configuration area was being edited so the shell can report it
    (Req #6: 'identify the affected configuration area when possible')."""

    def __init__(self, area: str, message: str):
        super().__init__(message)
        self.area = area
        self.message = message

    def __str__(self) -> str:
        return f"[{self.area}] {self.message}"


class ReferenceError_(Exception):
    """Raised by check_no_references when deleting an item would leave a
    dangling reference elsewhere in the config (Req #7)."""

    def __init__(self, item: str, referenced_by: Iterable[str]):
        refs = ", ".join(referenced_by)
        super().__init__(f"Cannot delete '{item}': still referenced by {refs}")
        self.item = item
        self.referenced_by = list(referenced_by)


def apply_edit(config, area: str, mutate_fn: Callable[[object], None]) -> None:
    """Run mutate_fn(draft) inside the library's atomic edit context, where
    `draft` is the deep copy edit_mode() yields -- NOT the original config.
    On successful exit, edit_mode() re-validates the draft and copies it
    back onto `config` itself; on ValidationError, the original is left
    untouched and this raises ValidationFailure instead.

    `area` is just a human label ("faculty", "course", "room", ...) used
    in error messages -- it is NOT used to decide what gets validated;
    edit_mode() always validates the complete config, which is the point.

    Usage:
        def _mutate(cfg):
            cfg.config.faculty.append(new_faculty_obj)
        apply_edit(config, "faculty", _mutate)
    """
    try:
        with config.edit_mode() as draft:
            mutate_fn(draft)
    except ValidationError as e:
        raise ValidationFailure(area, str(e)) from e


def check_no_references(name: str, referenced_by: Iterable[str]) -> None:
    """Call this BEFORE deleting a room/lab/faculty/course. Pass in the
    names of anything that still points at `name` (e.g. courses whose
    `faculty` list includes this person, a class pattern using this room).
    Raises ReferenceError_ if the list isn't empty.

    Each entity's delete_* command is responsible for building
    `referenced_by` by scanning the relevant parts of config -- that scan
    is domain-specific per entity, so it isn't generalized here. This just
    gives every delete_* command the same failure shape and message
    format (Req #7: 'account for cases where a room, lab, faculty member,
    or course is referenced elsewhere').
    """
    referenced_by = list(referenced_by)
    if referenced_by:
        raise ReferenceError_(name, referenced_by)