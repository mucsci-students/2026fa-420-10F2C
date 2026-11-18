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

Like every controller, this never builds HTTP responses (Section 20).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from app.schedule_export import ExportError, ScheduleExport, build_export
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
