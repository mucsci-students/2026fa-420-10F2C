"""
Why generation can fail, in plain words (used by the AI chat).

    diagnose_configuration()      "Why did it fail?", "check my configuration for problems"
    explain_no_feasible(request)  the paragraph the chat adds when a run finds no feasible schedule

The scheduler library validates a configuration's structure; what it cannot tell you before a run
is whether the pieces fit together. These are the usual reasons they don't, checked from the same
plain data the Configuration Editor pages use (no scheduler internals):

  * a course that needs more seats than any room it may use holds
  * a course that nobody can teach (no teacher listed and nobody prefers it)
  * faculty who must teach at least N credits in total, with fewer credits than that in the courses
  * courses with more credits than the faculty can teach at most

They are likely causes, not proof: the solver has the final word. The reply says so, and also lists
the newest changes, because "it worked before I deleted that room" is the most useful thing to know.
"""

from __future__ import annotations

from gui.ai.base import UNDO_CHIP, AiTool, NoArgs, Outcome, _join
from gui.ai.undo import recent_changes
from gui.controllers import courses, faculty, labs, rooms

MAX_EXAMPLES = 3
CHECK_CHIP = "Check the configuration for problems"


def _few(items: list[str]) -> str:
    shown = items[:MAX_EXAMPLES]
    more = f" and {len(items) - len(shown)} more" if len(items) > len(shown) else ""
    return _join(shown) + more


def find_problems(request) -> list[str]:
    """Plain sentences, most likely cause first. Empty when nothing obvious is wrong."""
    rows = courses.describe_courses(request).get("courses", [])
    room_size = {item["name"]: item["capacity"] for item in rooms.describe_rooms(request).get("rooms", [])}
    lab_size = {item["name"]: item["capacity"] for item in labs.describe_labs(request).get("labs", [])}
    people = faculty.describe_faculty(request).get("faculty", [])
    problems: list[str] = []

    # Faculty minimum and maximum credits against the credits the courses add up to.
    taught = sum(row["credits"] for row in rows)
    least = sum(person["minimum_credits"] for person in people)
    most = sum(person["maximum_credits"] for person in people)
    if people and rows and least > taught:
        problems.append(
            f"The faculty must teach at least {least} credits in total, but the courses only add up to {taught}. "
            "Add courses or lower the faculty minimums."
        )
    if people and rows and taught > most:
        problems.append(
            f"The courses add up to {taught} credits, but the faculty can teach at most {most} in total. "
            "Add faculty or raise their maximums."
        )

    # Courses nobody can teach.
    untaught = [row["display"] for row in rows if row["faculty"] is None and not row["derived_faculty"]]
    if untaught:
        problems.append(
            f"Nobody can teach {_few(untaught)}: no teacher is listed and no faculty member prefers "
            f"{'it' if len(untaught) == 1 else 'them'}."
        )

    # Courses that do not fit in the rooms they may use.
    crowded = []
    for row in rows:
        sizes = [room_size[name] for name in row["rooms"] if name in room_size]
        sizes = sizes or [lab_size[name] for name in row["labs"] if name in lab_size]
        if sizes and max(sizes) < row["capacity"]:
            crowded.append(f"{row['display']} needs {row['capacity']} seats but its rooms hold at most {max(sizes)}")
    if crowded:
        more = "; and more." if len(crowded) > MAX_EXAMPLES else "."
        problems.append("Too small: " + "; ".join(crowded[:MAX_EXAMPLES]) + more)
    return problems


def _recent_note(request) -> str:
    changes = recent_changes(request)
    if not changes:
        return ""
    return f" Your newest changes were: {'; '.join(changes)}. If it worked before them, undoing them may fix it."


OTHER_CAUSES = "faculty availability that is too tight, course conflicts, or class patterns that do not fit the time slots"


def explain_no_feasible(request) -> str:
    """The text added to "No feasible schedule was found": what was found, and what changed lately."""
    try:
        problems: list[str] | None = find_problems(request)
    except Exception:  # an explanation must never hide the real result, and must not claim a clean check either
        problems = None
    if problems:
        text = f" What I found: {' '.join(problems)} Other common causes are {OTHER_CAUSES}."
    elif problems is None:
        text = f" Common causes are {OTHER_CAUSES}."
    else:
        text = (
            " I found no obvious problem with room sizes, teachers or credit totals. Common causes are "
            f"{OTHER_CAUSES}."
        )
    return text + _recent_note(request)


def diagnose_configuration(request, args: NoArgs) -> Outcome:
    problems = find_problems(request)
    if problems:
        text = "I checked the configuration for the usual reasons a run finds no schedule:\n" + "\n".join(
            f"- {problem}" for problem in problems
        )
    else:
        text = (
            "I checked room sizes, teachers and credit totals and found nothing obviously wrong. If a run still "
            "finds no schedule, look at faculty availability, time slots, course conflicts and class patterns. "
            "The solver has the final word."
        )
    text += _recent_note(request)
    chips = (UNDO_CHIP,) if recent_changes(request, 1) else ()
    return Outcome(text, chips)


DIAGNOSE_TOOLS = [
    AiTool(
        "diagnose_configuration",
        "Check the open configuration for the usual reasons schedule generation finds no feasible schedule "
        "(rooms too small, a course nobody can teach, faculty credit totals) and list the newest changes. "
        "Use when the user asks why generation failed, or to check the configuration for problems.",
        NoArgs,
        diagnose_configuration,
    ),
]
