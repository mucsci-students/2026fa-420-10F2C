"""
Controller for exporting one schedule as a PDF (Sprint 4 Sections 5 and 5.4).

    export_pdf(request, index, orientation, selected, render) -> PdfFile

It picks the schedule, arranges it with app.schedule_export.build_export, and
hands the result to a renderer that draws the PDF. Every way this can fail
ends in a ControllerError with a message the user can act on, and nothing in
the session changes, whether the export works or not:

    * there are no schedules, or the schedule number doesn't exist
      (get_schedule's messages, shared with the JSON and CSV exports);
    * the orientation is not "rooms" or "faculty";
    * the chosen room, lab or faculty member is not in that schedule;
    * the renderer raises, or returns something that is not a PDF.

A schedule with no course sections is not an error: the export is labelled
empty (ScheduleExport.empty_label) and the renderer prints that label, as
Section 5.4 allows.

Overwrite protection: like the JSON and CSV exports, the view sends the PDF as
a download (gui/views.download_response), so the browser chooses where it goes
and asks before replacing a file. The app never writes the PDF to disk itself.

The renderer is passed in rather than imported, so this module does not
depend on a PDF library and its tests do not need one. A renderer is any
function ``render(export, title) -> bytes``; ``title`` identifies the
schedule, e.g. "Schedule 2 of 5".

The Schedule Viewer offers one "What to export" choice that names both the
orientation and the group (export_choices); parse_choice turns the chosen
value back into the (orientation, selected) pair export_pdf takes.

Like every controller, this never builds HTTP responses (Section 20).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from app.schedule_export import (
    BY_FACULTY,
    BY_ROOM_OR_LAB,
    EXPORT_ORIENTATIONS,
    ExportError,
    GroupKey,
    ScheduleExport,
    available_groups,
    build_export,
    export_grouping,
)
from app.schedule_view import FACULTY
from gui.controllers.errors import ControllerError
from gui.controllers.schedule_controller import get_schedule, schedule_count

logger = logging.getLogger(__name__)

PDF_CONTENT_TYPE = "application/pdf"

# Draws one export as a PDF. title identifies the schedule ("Schedule 2 of 5").
PdfRenderer = Callable[[ScheduleExport, str], bytes]

PDF_FAILED_MESSAGE = (
    "The PDF could not be created. Your schedules and configuration were not "
    "changed. Try again, or export the schedule as JSON or CSV instead."
)


# The headings of the "What to export" list, one per orientation.
ORIENTATION_LABELS = {BY_ROOM_OR_LAB: "By room or lab", BY_FACULTY: "By faculty"}

CHOOSE_EXPORT_MESSAGE = (
    "Choose what to export from the list. If the schedules changed since the "
    "page loaded, reload it and choose again."
)

# A choice is "<orientation>" for every group, or "<orientation>:<kind>:<name>"
# for one. Orientations and kinds have no colon, so a name may contain one.
_SEPARATOR = ":"

# A (value, label) list under one heading, as Django's grouped choices take it.
ChoiceGroup = tuple[str, list[tuple[str, str]]]


@dataclass(frozen=True)
class PdfFile:
    """A PDF ready to download: the view passes these to download_response()."""

    filename: str
    content: bytes
    title: str  # the schedule it shows, e.g. "Schedule 2 of 5"
    content_type: str = PDF_CONTENT_TYPE


def export_pdf(
    request,
    index: int,
    orientation: str,
    selected: tuple[str, str] | None,
    render: PdfRenderer,
) -> PdfFile:
    """Export schedule ``index`` (0-based) as a PDF.

    ``orientation`` is "rooms" (by room or lab) or "faculty". ``selected`` is
    one (kind, name) pair from app.schedule_export.available_groups, such as
    ("faculty", "Hogg") or ("lab", "Linux"), or None for every group.

    Raises ControllerError for anything that stops the export (see the module
    docstring). Nothing in the session changes either way.
    """
    assignments = get_schedule(request, index)
    title = f"Schedule {index + 1} of {schedule_count(request)}"

    try:
        export = build_export(assignments, orientation, selected)
    except ExportError as error:
        raise ControllerError(str(error)) from error

    try:
        content = render(export, title)
    except Exception as error:  # the renderer is outside this app's control
        logger.exception("PDF renderer failed for %s", title)
        raise ControllerError(PDF_FAILED_MESSAGE) from error

    if not _is_pdf(content):
        logger.error("PDF renderer returned something that is not a PDF for %s", title)
        raise ControllerError(PDF_FAILED_MESSAGE)

    return PdfFile(
        filename=pdf_filename(index, export),
        content=bytes(content),
        title=title,
    )


def pdf_filename(index: int, export: ScheduleExport) -> str:
    """schedule-<n>-<what>.pdf, with n as shown to the user (1-based).

    <what> is "all-rooms-and-labs", "all-faculty", or the selected group with
    its kind, so a room and a lab with the same name get different files:
    "room-roddy-147", "lab-linux", "faculty-hogg".
    """
    if export.selected is None:
        what = f"all-{export.grouping.plural}"
    else:
        what = f"{export.selected.kind}-{export.selected.name}"
    return f"schedule-{index + 1}-{_slug(what)}.pdf"


def _slug(text: str) -> str:
    """Lower case, with every run of other characters turned into one dash."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "export"


def _is_pdf(content: object) -> bool:
    """True for non-empty bytes that start like a PDF file does."""
    return isinstance(content, (bytes, bytearray)) and content.startswith(b"%PDF-")


def export_choices(request, index: int) -> list[ChoiceGroup]:
    """What schedule ``index`` (0-based) can be exported as, for the viewer's list.

    One heading per orientation. Each starts with every group ("All rooms and
    labs", "All faculty"), followed by each room and lab ("Room: Roddy 136",
    "Lab: Roddy 147") or each faculty member, in the order the PDF lists them.
    A room and a lab with the same name are two choices.

    Raises ControllerError when there is no such schedule.
    """
    assignments = get_schedule(request, index)
    choices = []
    for orientation in EXPORT_ORIENTATIONS:
        options = [(orientation, f"All {export_grouping(orientation).plural}")]
        options.extend(
            (choice_value(orientation, group), _group_label(group))
            for group in available_groups(assignments, orientation)
        )
        choices.append((ORIENTATION_LABELS[orientation], options))
    return choices


def choice_value(orientation: str, group: GroupKey | None = None) -> str:
    """The list value for one orientation and group (None = every group)."""
    if group is None:
        return orientation
    return _SEPARATOR.join((orientation, group.kind, group.name))


def parse_choice(value: str) -> tuple[str, tuple[str, str] | None]:
    """The (orientation, selected) pair a list value stands for.

    Raises ControllerError for a value no list would contain. Whether the
    group is really in the schedule is checked by export_pdf.
    """
    orientation, *rest = value.split(_SEPARATOR, 2)
    if orientation not in EXPORT_ORIENTATIONS or len(rest) not in (0, 2):
        raise ControllerError(CHOOSE_EXPORT_MESSAGE)
    if not rest:
        return orientation, None
    kind, name = rest
    if not name:
        raise ControllerError(CHOOSE_EXPORT_MESSAGE)
    return orientation, (kind, name)


def _group_label(group: GroupKey) -> str:
    if group.kind == FACULTY:
        return group.name
    return f"{group.kind.capitalize()}: {group.name}"
