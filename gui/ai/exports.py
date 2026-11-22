"""
The AI tool that exports a schedule as a PDF (Sprint 4 Section 5, through the assistant).

    export_schedule_pdf   checks which schedule, which orientation (by room or lab, or by faculty) and,
                          optionally, which one room, lab or faculty member, then shows an Export PDF button.
                          The button is the Schedule Viewer's own PDF export (gui:schedule_export_pdf), so
                          there is one export: the same checks, the same PDF, the same browser download.

Like saving a configuration (gui/ai/lifecycle.py), the tool never downloads anything itself. It only
prepares the button, and the user's click starts the download. The application cannot see whether the
browser finished it, so the reply never says the PDF was saved.

Which schedule: the one the user names, otherwise the one open in the Schedule Viewer (the chat sends
its number; see gui/ai/locks.note_viewed_schedule), otherwise schedule 1, and the reply says so.

A name is matched the way every other tool matches one (gui/ai/base.find_name): "room 136" finds
"Roddy 136" and "hogg" finds "Hogg". A name that is both a room and a lab in that schedule is asked
about, never guessed.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schedule_export import (
    BY_FACULTY,
    BY_ROOM_OR_LAB,
    GroupKey,
    available_groups,
    export_grouping,
)
from app.schedule_view import LAB, ROOM
from gui.ai.base import AiTool, Outcome, find_name, not_found
from gui.ai.locks import VIEWED_SCHEDULE_ATTR
from gui.controllers import pdf_export, schedule_controller
from gui.controllers.errors import ControllerError

DOWNLOAD_NOTE = (
    "Your browser decides where the file goes and what happens if a file with that name already "
    "exists, and this app cannot tell whether the download finished."
)
NO_SCHEDULES = (
    "There are no schedules to export yet. Generate schedules, or load a schedule file in the "
    "Schedule Viewer, then ask me again."
)
GENERATE_CHIP = "Generate schedules"


class RoomOrLab(ControllerError):
    """A name that is both a room and a lab in the schedule: the user is asked which."""

    def __init__(self, name: str, number: int):
        self.name = name
        super().__init__(
            f"'{name}' is both a room and a lab in schedule {number}. Say which one to export."
        )


class ExportSchedulePdfArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orientation: Literal["rooms", "faculty"] = Field(
        description=(
            '"rooms" for a PDF organised by room and lab, "faculty" for one organised by faculty '
            "member. A request about a room or lab means rooms; one about a person means faculty."
        ),
    )
    schedule: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Schedule number (1-based). Leave it out: the application uses the schedule the user is "
            "looking at. Only set it when the user names a schedule ('schedule 3')."
        ),
    )
    name: str | None = Field(
        default=None,
        description=(
            "One room, lab or faculty member, only if the user asked for just one. Leave it out for "
            "every room and lab, or every faculty member."
        ),
    )
    kind: Literal["room", "lab"] | None = Field(
        default=None,
        description='"room" or "lab", only when the user said which (with orientation "rooms").',
    )


def export_schedule_pdf(request, args: ExportSchedulePdfArgs) -> Outcome:
    count = schedule_controller.schedule_count(request)
    if count == 0:
        return Outcome(NO_SCHEDULES, (GENERATE_CHIP,))

    if args.schedule is not None:
        number, assumed = args.schedule, False
        if number > count:
            return Outcome(
                f"There {'is only 1 schedule' if count == 1 else f'are {count} schedules'}, so there is "
                f"no schedule {number}. Ask for schedule 1{'' if count == 1 else f' to {count}'}."
            )
    else:
        viewed = getattr(request, VIEWED_SCHEDULE_ATTR, None)
        if viewed is None:
            number, assumed = (
                1,
                count > 1,
            )  # with one schedule there is nothing to explain
        else:
            number, assumed = (viewed if 1 <= viewed <= count else 1), False
    which = f"Schedule {number} of {count}"
    if assumed:
        which += (
            " (no schedule is open in the Schedule Viewer, so I used schedule 1; ask for another "
            "number to export a different one)"
        )

    if args.name is None:
        group = None
        what = f"all {export_grouping(args.orientation).plural}"
    else:
        try:
            group = _find_group(request, number - 1, args)
        except RoomOrLab as error:
            return Outcome(
                error.message,
                tuple(
                    f"Export {kind} {error.name} from schedule {number} as a PDF"
                    for kind in (ROOM, LAB)
                ),
            )
        except ControllerError as error:
            return Outcome(error.message)
        what = _describe(group)

    return Outcome(
        f"Ready to export {which}, {what}, as a PDF (US Letter, one table per "
        f"{'room or lab' if args.orientation == BY_ROOM_OR_LAB else 'faculty member'}). "
        f"Click Export PDF to download it. {DOWNLOAD_NOTE}",
        action={
            "kind": "pdf",
            "schedule": number,
            "what": pdf_export.choice_value(args.orientation, group),
        },
    )


def _find_group(request, index: int, args: ExportSchedulePdfArgs) -> GroupKey:
    """The one room, lab or faculty member the user asked for, in that schedule."""
    groups = available_groups(
        schedule_controller.get_schedule(request, index), args.orientation
    )
    if args.orientation == BY_ROOM_OR_LAB and args.kind is not None:
        groups = [group for group in groups if group.kind == args.kind]
    label = _label(args)
    names = sorted({group.name for group in groups})
    found = find_name(args.name or "", names)
    if found is None:
        raise ControllerError(
            f"{not_found(label, args.name or '', names)} (in schedule {index + 1})"
        )
    matches = [group for group in groups if group.name == found]
    if len(matches) > 1:  # a room and a lab with the same name
        raise RoomOrLab(found, index + 1)
    return matches[0]


def _label(args: ExportSchedulePdfArgs) -> str:
    if args.orientation == BY_FACULTY:
        return "faculty member"
    return args.kind or "room or lab"


def _describe(group: GroupKey) -> str:
    if group.kind in (ROOM, LAB):
        return f"{group.kind} {group.name} only"
    return f"{group.name} only"


EXPORT_TOOLS: tuple[AiTool, ...] = (
    AiTool(
        "export_schedule_pdf",
        "Offer to download a schedule as a print-friendly PDF, organised by room and lab or by faculty, for "
        "every room/lab or faculty member or for just one. Use for PDF, print or printable-schedule requests. "
        "It only shows an Export PDF button: never say the PDF was downloaded or saved.",
        ExportSchedulePdfArgs,
        export_schedule_pdf,
        needs_config=False,
    ),
)
