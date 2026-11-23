"""Print-friendly PDF of a schedule export (Sprint 4 Section 5.3).

View layer (Section 20), presentation only. What an export contains -- its
sections, rows and their order -- is decided by the model in
app/schedule_export.py. This module only puts a ``ScheduleExport`` on paper,
and it returns the PDF as bytes: it writes no files and handles no requests.

``ScheduleDocument`` is the Template Method pattern. ``build()`` fixes the
steps every schedule PDF follows:

    1. a title block naming the schedule and what the export covers
    2. for each section, a table whose first two rows -- the section heading
       and the column headings -- repeat on every page the section runs onto
    3. or, when there is nothing to export, a line saying so
    4. a header and page number on every page

The two concrete documents supply only what differs between a room/lab export
and a faculty export: the document's name, how a section is headed, and which
columns its table has.

Page: US Letter, portrait, 0.75 inch margins. Black text on white with gray
rules and light gray heading bands, so it reads the same in grayscale. Long
names wrap inside their cell instead of being cut off.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    CondPageBreak,
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.schedule_export import (
    BY_FACULTY,
    BY_ROOM_OR_LAB,
    NO_MEETING_TIMES_LABEL,
    ExportRow,
    ExportSection,
    ScheduleExport,
)
from gui.calendar_layout import range_text
from gui.constants import TIME_FORMAT_24

PAPER_NAME = "US Letter"
PAGE_SIZE = letter
MARGIN = 0.75 * inch
CONTENT_WIDTH = PAGE_SIZE[0] - 2 * MARGIN

DAY_ABBREVIATIONS = {
    "MON": "Mon",
    "TUE": "Tue",
    "WED": "Wed",
    "THU": "Thu",
    "FRI": "Fri",
}

# Grayscale only: nothing on the page depends on color.
RULE = colors.Color(0.55, 0.55, 0.55)
SECTION_BAND = colors.Color(0.82, 0.82, 0.82)
COLUMN_BAND = colors.Color(0.93, 0.93, 0.93)

_TITLE = ParagraphStyle(
    "title", fontName="Helvetica-Bold", fontSize=16, leading=20, alignment=TA_LEFT
)
_SUBTITLE = ParagraphStyle("subtitle", fontName="Helvetica", fontSize=11, leading=14)
_SECTION = ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=12, leading=15)
_COLUMN = ParagraphStyle("column", fontName="Helvetica-Bold", fontSize=9, leading=11)
_CELL = ParagraphStyle("cell", fontName="Helvetica", fontSize=10, leading=12.5)
_NOTE = ParagraphStyle("note", fontName="Helvetica-Oblique", fontSize=11, leading=14)

HEADER_FONT = ("Helvetica", 8)

# A section is not started in the last bit of a page: without room for its two
# heading rows and a couple of meetings it begins on the next page instead.
MIN_SECTION_START = 1.3 * inch


@dataclass(frozen=True)
class Column:
    """One column of a section's table."""

    heading: str
    share: float  # of the content width; a table's shares add up to 1
    text: Callable[[ExportRow], str]


def text_paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    """Plain text as a wrapping paragraph. Names are escaped, so an ampersand or
    an angle bracket in a course or faculty name prints as itself."""
    return Paragraph(escape(text), style)


def fit(text: str, width: float) -> str:
    """The running header is one line, so text too long for its half of the
    line is cut with an ellipsis there. The title block and the section
    headings always carry the full text."""
    if stringWidth(text, *HEADER_FONT) <= width:
        return text
    while text and stringWidth(text + "\u2026", *HEADER_FONT) > width:
        text = text[:-1]
    return text.rstrip() + "\u2026"


def days_text(row: ExportRow) -> str:
    """ "Mon, Wed, Fri", or "No meeting times" for a section that never meets."""
    if not row.has_meeting_times:
        return NO_MEETING_TIMES_LABEL
    return ", ".join(DAY_ABBREVIATIONS.get(day, day) for day in row.days)


def location_text(row: ExportRow) -> str:
    """ "Roddy 147 (lab)", or "No room assigned" -- never an invented room."""
    if row.resource is None:
        return row.location_label
    return f"{row.location_label} ({row.location_kind})"


class ScheduleDocument(ABC):
    """A schedule export as a PDF. Subclasses say how their orientation is
    named, headed and laid out in columns; ``build()`` does the rest."""

    #: The export's name on the page: "By room or lab".
    name: str

    def __init__(
        self,
        export: ScheduleExport,
        schedule_label: str,
        time_format: str = TIME_FORMAT_24,
    ) -> None:
        self.export = export
        self.schedule_label = schedule_label  # e.g. "Schedule 2 of 5"
        self.time_format = time_format

    # ------------------------------------------------------------------ #
    #  The steps that differ between orientations
    # ------------------------------------------------------------------ #
    @abstractmethod
    def section_heading(self, section: ExportSection) -> str:
        """The heading of one section: "Lab: Roddy 147", "Faculty: Hogg"."""

    @abstractmethod
    def columns(self) -> Sequence[Column]:
        """The columns of a section's table, left to right."""

    # ------------------------------------------------------------------ #
    #  The template method
    # ------------------------------------------------------------------ #
    def build(self) -> bytes:
        """The whole document as PDF bytes."""
        story: list[Flowable] = [*self.title_block()]
        if self.export.is_empty:
            story.extend(self.empty_block())
        for section in self.export.sections:
            story.extend(self.section_block(section))

        buffer = BytesIO()
        document = SimpleDocTemplate(
            buffer,
            pagesize=PAGE_SIZE,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=MARGIN + 0.3 * inch,  # room for the running header
            bottomMargin=MARGIN,
            title=self.title,
            author="Course Scheduler",
            subject=self.subtitle,
            invariant=1,  # the same export always gives the same bytes
        )
        document.build(
            story, onFirstPage=self.page_furniture, onLaterPages=self.page_furniture
        )
        return buffer.getvalue()

    # ------------------------------------------------------------------ #
    #  The steps every schedule PDF shares
    # ------------------------------------------------------------------ #
    @property
    def title(self) -> str:
        """Identifies the exported schedule and its grouping."""
        return f"{self.schedule_label} — {self.name}"

    @property
    def subtitle(self) -> str:
        """Which groups the export covers: "All rooms and labs", "Hogg (faculty)"."""
        return self.export.scope

    def title_block(self) -> list[Flowable]:
        return [
            text_paragraph(self.title, _TITLE),
            text_paragraph(self.subtitle, _SUBTITLE),
            Spacer(1, 0.2 * inch),
        ]

    def empty_block(self) -> list[Flowable]:
        return [text_paragraph(self.export.empty_label, _NOTE)]

    def section_block(self, section: ExportSection) -> list[Flowable]:
        """One section: a table headed by the section heading and the column
        headings, both repeated on every page the table continues onto."""
        columns = self.columns()
        heading = text_paragraph(self.section_heading(section), _SECTION)
        rows: list[list[Paragraph | str]] = [
            [heading, *[""] * (len(columns) - 1)],
            [text_paragraph(column.heading, _COLUMN) for column in columns],
        ]
        rows.extend(
            [text_paragraph(column.text(row), _CELL) for column in columns]
            for row in section.rows
        )
        table = Table(
            rows,
            colWidths=[column.share * CONTENT_WIDTH for column in columns],
            repeatRows=2,
        )
        table.setStyle(
            TableStyle(
                [
                    ("SPAN", (0, 0), (-1, 0)),
                    ("BACKGROUND", (0, 0), (-1, 0), SECTION_BAND),
                    ("BACKGROUND", (0, 1), (-1, 1), COLUMN_BAND),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.5, RULE),
                    ("BOX", (0, 0), (-1, -1), 0.75, RULE),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return [CondPageBreak(MIN_SECTION_START), table, Spacer(1, 0.25 * inch)]

    def page_furniture(self, canvas: Canvas, document: SimpleDocTemplate) -> None:
        """The running header and the page number, drawn on every page."""
        canvas.saveState()
        top = PAGE_SIZE[1] - MARGIN
        canvas.setFont(*HEADER_FONT)
        canvas.drawString(MARGIN, top + 4, fit(self.title, CONTENT_WIDTH * 0.48))
        canvas.drawRightString(
            PAGE_SIZE[0] - MARGIN, top + 4, fit(self.subtitle, CONTENT_WIDTH * 0.48)
        )
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, top, PAGE_SIZE[0] - MARGIN, top)
        canvas.drawCentredString(
            PAGE_SIZE[0] / 2, MARGIN - 0.3 * inch, f"Page {canvas.getPageNumber()}"
        )
        canvas.restoreState()

    # ------------------------------------------------------------------ #
    #  Column text the two orientations share
    # ------------------------------------------------------------------ #
    def time_text(self, row: ExportRow) -> str:
        """Start and end in the chosen clock format; nothing when it never meets."""
        if not row.has_meeting_times:
            return ""
        return range_text(row.start, row.end, self.time_format)

    def shared_columns(self) -> tuple[Column, Column]:
        return (
            Column("Course", 0.17, lambda row: row.course_name),
            Column("Section", 0.10, lambda row: row.section),
        )

    def time_columns(self) -> tuple[Column, Column]:
        return (
            Column("Days", 0.21, days_text),
            Column("Time", 0.22, self.time_text),
        )


class RoomLabDocument(ScheduleDocument):
    """By room or lab: each section is one room or one lab, and its table says
    who teaches there (Section 5.1)."""

    name = "By room or lab"

    def section_heading(self, section: ExportSection) -> str:
        if section.is_unassigned:
            return section.title
        return f"{section.kind.capitalize()}: {section.title}"

    def columns(self) -> Sequence[Column]:
        return (
            *self.shared_columns(),
            Column("Faculty", 0.30, lambda row: row.faculty_label),
            *self.time_columns(),
        )


class FacultyDocument(ScheduleDocument):
    """By faculty: each section is one faculty member, and its table says where
    each meeting is, or that it has no room (Section 5.2)."""

    name = "By faculty"

    def section_heading(self, section: ExportSection) -> str:
        if section.is_unassigned:
            return section.title
        return f"Faculty: {section.title}"

    def columns(self) -> Sequence[Column]:
        return (
            *self.shared_columns(),
            Column("Room or lab", 0.30, location_text),
            *self.time_columns(),
        )


DOCUMENTS: dict[str, type[ScheduleDocument]] = {
    BY_ROOM_OR_LAB: RoomLabDocument,
    BY_FACULTY: FacultyDocument,
}


def render_pdf(
    export: ScheduleExport, schedule_label: str, time_format: str = TIME_FORMAT_24
) -> bytes:
    """A schedule export as PDF bytes.

    ``schedule_label`` names the schedule on every page ("Schedule 2 of 5").
    ``time_format`` is the viewer's clock choice; times are written the same
    way throughout the document.
    """
    document = DOCUMENTS[export.orientation]
    return document(export, schedule_label, time_format).build()
