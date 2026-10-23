"""
One place that knows how the configuration's records point at each other
(Sprint 2 Sections 10, 11, 12).

Rooms, labs, faculty, courses and class patterns are all linked by NAME or ID
rather than by object, so deleting one can leave dangling references behind.
Instead of each page inventing its own "In use by ..." rule, every kind of
record is described here once and the delete pages share the same flow:

    usage(config, kind, ident)    -> the "who uses this?" summary for list pages
    plan(config, kind, ident)     -> everything the confirmation page shows:
                                     what will change, which course sections
                                     would go too, and anything that blocks it
    resolve(plan)                 -> checks the delete is allowed: raises when
                                     something blocks it
    build(config, kind, ident, plan)
                                  -> (mutate, notices): `mutate(draft)` does the
                                     whole cascade on an edit-mode draft, so the
                                     scheduler library validates the COMPLETE
                                     result and rolls it all back on failure

THE RULES (what a delete does to the things that point at it)
    A delete only REMOVES references. It never puts a different record in the
    deleted one's place: deleting the lab "Mac" does not make the lab "Linux"
    take over its course sections.

    The review page lists everything a delete will change, including any course
    sections that are deleted too, and one click on its Delete button does it
    all. The result can be undone.

    room      removed from course room lists and from faculty room preferences;
              a section whose ONLY room it was cannot be scheduled any more, so
              it is deleted too
    lab       removed from course lab lists and faculty lab preferences; a
              section whose only lab it was is simply left without a lab (the
              scheduler library still validates the result)
    faculty   removed from explicit course assignments and from their own
              preferences; a section that assigned only them goes back to "the
              scheduler chooses among those who prefer it" when someone else
              prefers the course, and otherwise (or when they were the only
              person who prefers a course with no explicit assignment) the
              section is deleted too
    course    (the LAST section of a course id) removed from other courses'
              conflict lists and from faculty course preferences
    pattern   when it is the only enabled pattern for its credit value, the
              courses with that credit value cannot be scheduled any more, so
              deleting it also deletes those sections

Controller-layer code: no HTTP, no templates (Section 20). It works on a
configuration object it is given, so it needs no session.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.commands.courses import course_display_name
from gui.controllers.errors import ControllerError

KINDS = ("room", "lab", "faculty", "course", "pattern")


# ---------------------------------------------------------------------- #
#  Plain-data shape the pages render
# ---------------------------------------------------------------------- #
@dataclass
class Plan:
    kind: str
    ident: object
    name: str                                 # shown to the user
    effects: list = field(default_factory=list)   # one line per kind of change
    groups: list = field(default_factory=list)    # [{"title", "names"}] the affected records
    blockers: list = field(default_factory=list)
    removes_courses: list = field(default_factory=list)   # course positions that go too

    @property
    def in_use(self) -> bool:
        return bool(self.effects or self.removes_courses)

    @property
    def blocked(self) -> bool:
        return bool(self.blockers)


def _plural(count: int, noun: str, plural: str | None = None) -> str:
    return f"{count} {noun if count == 1 else (plural or noun + 's')}"


def _names(names, limit: int = 3) -> str:
    names = list(names)
    return ", ".join(names) if len(names) <= limit else ", ".join(names[:limit]) + f" and {len(names) - limit} more"


def _sections(config) -> list[tuple[int, str, object]]:
    """(position, display name, course) for every section, in list order."""
    seen: dict[str, int] = {}
    return [(i, course_display_name(c, seen), c) for i, c in enumerate(config.config.courses)]


def _is_last_section(config, index: int) -> bool:
    course_id = config.config.courses[index].course_id
    return not any(
        other.course_id == course_id for i, other in enumerate(config.config.courses) if i != index
    )


def _drop_course_ids(draft, ids: set) -> None:
    """Remove references to course ids that no longer have any section."""
    for other in draft.config.courses:
        if set(other.conflicts or []) & ids:
            other.conflicts = [c for c in other.conflicts if c not in ids]
    for person in draft.config.faculty:
        preferences = dict(person.course_preferences or {})
        if set(preferences) & ids:
            person.course_preferences = {k: v for k, v in preferences.items() if k not in ids}


def _delete_sections(draft, positions) -> None:
    """Delete the sections at `positions` and clean up the course ids that no
    longer have any section left (conflict lists, faculty course preferences)."""
    positions = sorted(set(positions), reverse=True)
    if not positions:
        return
    courses = draft.config.courses
    ids = {courses[position].course_id for position in positions}
    for position in positions:
        del courses[position]
    gone = {course_id for course_id in ids if not any(c.course_id == course_id for c in courses)}
    if gone:
        _drop_course_ids(draft, gone)


def _also_deleted_effects(plan: Plan, dependents, why: str) -> None:
    """Describe the sections that go with the record."""
    count = len(dependents)
    plan.effects.append(f"{_plural(count, 'course section')} {why}.")
    plan.effects.append(
        f"{'That section is' if count == 1 else 'Those sections are'} deleted along with it "
        f"(and removed from any conflict lists and faculty preferences)."
    )
    plan.groups.append({"title": "Course sections that would be deleted", "names": [d for _, d, _ in dependents]})
    plan.removes_courses = [i for i, _, _ in dependents]


def _also_deleted_notice(config, plan: Plan) -> list[str]:
    if not plan.removes_courses:
        return []
    wanted = set(plan.removes_courses)
    names = [display for i, display, _ in _sections(config) if i in wanted]
    return [f"Also deleted {_plural(len(names), 'course section')}: {_names(names, 4)}."]


# ---------------------------------------------------------------------- #
#  Rooms and labs
# ---------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Resource:
    label: str
    collection: str        # attribute of config.config holding the records
    course_field: str      # attribute on a course listing resource names
    preference_field: str  # attribute on faculty keyed by resource name
    required: bool         # a section cannot exist without one (rooms), or can (labs)


_RESOURCES = {
    "room": _Resource("room", "rooms", "room", "room_preferences", True),
    "lab": _Resource("lab", "labs", "lab", "lab_preferences", False),
}


def _resource_record(config, res: _Resource, name: str):
    record = next((r for r in getattr(config.config, res.collection) if r.name == name), None)
    if record is None:
        raise ControllerError(
            f"{res.label.capitalize()} '{name}' no longer exists. Refresh the page and try again."
        )
    return record


def _resource_usage_rows(config, res: _Resource, name: str):
    sections = [
        (i, display, course)
        for i, display, course in _sections(config)
        if name in (getattr(course, res.course_field, None) or [])
    ]
    faculty = [
        person.name
        for person in config.config.faculty
        if name in (getattr(person, res.preference_field, None) or {})
    ]
    return sections, faculty


def _only_resource(res: _Resource, course, name: str) -> bool:
    return list(getattr(course, res.course_field)) == [name]


def _usage_resource(config, res: _Resource, name: str) -> dict:
    sections, faculty = _resource_usage_rows(config, res, name)
    groups = []
    if sections:
        course_ids = list(dict.fromkeys(course.course_id for _, _, course in sections))
        groups.append(
            {
                "chip": _plural(len(course_ids), "course"),
                "tone": "info",
                "title": "Courses",
                "names": course_ids,
            }
        )
    if faculty:
        groups.append(
            {
                "chip": _plural(len(faculty), "faculty preference"),
                "tone": "",
                "title": "Faculty preferences",
                "names": faculty,
            }
        )
    return {"in_use": bool(groups), "groups": groups}


def _plan_resource(config, res: _Resource, name: str) -> Plan:
    _resource_record(config, res, name)
    plan = Plan(res.label, name, name)
    if res.required and len(getattr(config.config, res.collection)) <= 1:
        plan.blockers.append(
            f"'{name}' is the only {res.label}. Add another {res.label} first -- "
            f"a configuration needs at least one."
        )
        return plan

    sections, faculty = _resource_usage_rows(config, res, name)
    sole = [item for item in sections if _only_resource(res, item[2], name)]
    kept = [item for item in sections if item not in sole] if res.required else sections

    if kept:
        course_ids = list(dict.fromkeys(course.course_id for _, _, course in kept))
        plan.effects.append(
            f"It is removed from {_plural(len(kept), 'course section')} "
            f"({_plural(len(course_ids), 'course')})."
        )
        plan.groups.append({"title": "Course sections", "names": [display for _, display, _ in kept]})
    if faculty:
        plan.effects.append(
            f"Its {res.label} preference is removed for {_plural(len(faculty), 'faculty member')}."
        )
        plan.groups.append({"title": "Faculty preferences", "names": faculty})

    if sole and res.required:
        _also_deleted_effects(
            plan,
            sole,
            f"list only this {res.label}, so {'it' if len(sole) == 1 else 'they'} could not be scheduled without it",
        )
    elif sole:
        plan.effects.append(
            f"{_plural(len(sole), 'course section')} list{'s' if len(sole) == 1 else ''} only this "
            f"{res.label} and will be left without {'one' if len(sole) == 1 else 'any'}. "
            f"No other {res.label} is put in its place."
        )
        plan.groups.append({"title": f"Sections left without a {res.label}", "names": [d for _, d, _ in sole]})
    return plan


def _build_resource(config, res: _Resource, name: str, plan: Plan):
    doomed = set(plan.removes_courses)

    def mutate(draft):
        for position, course in enumerate(draft.config.courses):
            if position in doomed:
                continue
            names = list(getattr(course, res.course_field, None) or [])
            if name in names:
                setattr(course, res.course_field, [item for item in names if item != name])
        for person in draft.config.faculty:
            preferences = dict(getattr(person, res.preference_field, None) or {})
            if name in preferences:
                del preferences[name]
                setattr(person, res.preference_field, preferences)
        records = getattr(draft.config, res.collection)
        del records[next(i for i, record in enumerate(records) if record.name == name)]
        _delete_sections(draft, doomed)

    notices: list[str] = []
    sections, faculty = _resource_usage_rows(config, res, name)
    kept = [item for item in sections if item[0] not in doomed]
    parts = []
    if kept:
        parts.append(_plural(len(kept), "course section"))
    if faculty:
        parts.append(_plural(len(faculty), f"faculty {res.label} preference"))
    if parts:
        notices.append(f"Removed '{name}' from {' and '.join(parts)}.")
    left = [item for item in kept if _only_resource(res, item[2], name)]
    if left and not res.required:
        notices.append(
            f"{_plural(len(left), 'course section')} now {'has' if len(left) == 1 else 'have'} no {res.label}."
        )
    notices += _also_deleted_notice(config, plan)
    return mutate, notices


# ---------------------------------------------------------------------- #
#  Faculty
# ---------------------------------------------------------------------- #
def _faculty_record(config, name: str):
    person = next((p for p in config.config.faculty if p.name == name), None)
    if person is None:
        raise ControllerError(f"Faculty member '{name}' no longer exists. Refresh the page and try again.")
    return person


def _faculty_sections(config, name: str):
    """(explicit sections, sections that only this person's preference staffs)."""
    explicit, derived_only = [], []
    for index, display, course in _sections(config):
        assigned = getattr(course, "faculty", None)
        if assigned is not None:
            if name in assigned:
                explicit.append((index, display, course))
            continue
        preferring = [p.name for p in config.config.faculty if course.course_id in (p.course_preferences or {})]
        if preferring == [name]:
            derived_only.append((index, display, course))
    return explicit, derived_only


def _someone_else_prefers(config, name: str, course) -> bool:
    return any(
        person.name != name and course.course_id in (person.course_preferences or {})
        for person in config.config.faculty
    )


def _faculty_split(config, name: str):
    """Sort the sections this person affects into:
        shared    assigned to them AND someone else (they are just removed)
        handed    assigned to only them, but someone else prefers the course, so
                  the scheduler chooses among those who prefer it
        doomed    nobody else could teach them, so they are deleted too
    """
    explicit, derived_only = _faculty_sections(config, name)
    shared, handed, doomed = [], [], list(derived_only)
    for item in explicit:
        course = item[2]
        if list(course.faculty) != [name]:
            shared.append(item)
        elif _someone_else_prefers(config, name, course):
            handed.append(item)
        else:
            doomed.append(item)
    return shared, handed, sorted(doomed, key=lambda item: item[0])


def _usage_faculty(config, name: str) -> dict:
    explicit, derived_only = _faculty_sections(config, name)
    groups = []
    if explicit:
        course_ids = list(dict.fromkeys(course.course_id for _, _, course in explicit))
        groups.append(
            {
                "chip": _plural(len(course_ids), "course"),
                "tone": "info",
                "title": "Assigned to",
                "names": [display for _, display, _ in explicit],
            }
        )
    if derived_only:
        groups.append(
            {
                "chip": f"only candidate for {_plural(len(derived_only), 'section')}",
                "tone": "",
                "title": "Only candidate for",
                "names": [display for _, display, _ in derived_only],
            }
        )
    return {"in_use": bool(groups), "groups": groups}


def _plan_faculty(config, name: str) -> Plan:
    _faculty_record(config, name)
    plan = Plan("faculty", name, name)
    if len(config.config.faculty) <= 1:
        plan.blockers.append(
            f"'{name}' is the only faculty member. Add another one first -- a configuration needs at least one."
        )
        return plan
    shared, handed, doomed = _faculty_split(config, name)
    if shared:
        plan.effects.append(f"They are removed from {_plural(len(shared), 'course section')} that also have other faculty.")
        plan.groups.append({"title": "Course sections", "names": [display for _, display, _ in shared]})
    if handed:
        plan.effects.append(
            f"{_plural(len(handed), 'course section')} assign{'s' if len(handed) == 1 else ''} only them. "
            f"{'It' if len(handed) == 1 else 'They'} will go back to \"the scheduler chooses\" "
            f"from the faculty who prefer {'it' if len(handed) == 1 else 'them'}; nobody is named in their place."
        )
        plan.groups.append({"title": "Sections the scheduler will staff", "names": [display for _, display, _ in handed]})
    if doomed:
        _also_deleted_effects(
            plan,
            doomed,
            "could not be taught by anyone else, so "
            + ("it" if len(doomed) == 1 else "they")
            + " could not be scheduled without them",
        )
    return plan


def _build_faculty(config, name: str, plan: Plan):
    doomed = set(plan.removes_courses)

    def mutate(draft):
        for position, course in enumerate(draft.config.courses):
            if position in doomed:
                continue
            assigned = getattr(course, "faculty", None)
            if assigned is not None and name in assigned:
                remaining = [item for item in assigned if item != name]
                course.faculty = remaining or None
        people = draft.config.faculty
        del people[next(i for i, person in enumerate(people) if person.name == name)]
        _delete_sections(draft, doomed)

    shared, handed, _ = _faculty_split(config, name)
    notices = []
    removed = len(shared) + len(handed)
    if removed:
        notices.append(f"Removed '{name}' from {_plural(removed, 'course section')}.")
    if handed:
        notices.append(
            f"{_plural(len(handed), 'course section')} will be staffed by the scheduler from the "
            f"faculty who prefer {'it' if len(handed) == 1 else 'them'}."
        )
    notices += _also_deleted_notice(config, plan)
    return mutate, notices


# ---------------------------------------------------------------------- #
#  Courses (one section)
# ---------------------------------------------------------------------- #
def _course_at(config, index):
    courses = config.config.courses
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(courses):
        raise ControllerError("That course no longer exists. Refresh the page and try again.")
    return courses[index]


def _course_dependents(config, index: int):
    """(sections listing it as a conflict, faculty preferring it) -- only when
    this is the LAST section of its course id (otherwise the id lives on)."""
    if not _is_last_section(config, index):
        return [], []
    course_id = config.config.courses[index].course_id
    conflicts = [
        display
        for position, display, other in _sections(config)
        if position != index and course_id in (other.conflicts or [])
    ]
    faculty = [p.name for p in config.config.faculty if course_id in (p.course_preferences or {})]
    return conflicts, faculty


def _usage_course(config, index: int) -> dict:
    _course_at(config, index)
    conflicts, faculty = _course_dependents(config, index)
    groups = []
    if conflicts:
        groups.append({"chip": _plural(len(conflicts), "conflict"), "tone": "info", "title": "Listed as a conflict by", "names": conflicts})
    if faculty:
        groups.append({"chip": _plural(len(faculty), "faculty preference"), "tone": "", "title": "Preferred by", "names": faculty})
    return {"in_use": bool(groups), "groups": groups}


def _plan_course(config, index: int) -> Plan:
    course = _course_at(config, index)
    display = next(d for i, d, _ in _sections(config) if i == index)
    plan = Plan("course", index, display)
    if len(config.config.courses) <= 1:
        plan.blockers.append(
            f"'{display}' is the only course. Add another course first -- a configuration needs at least one."
        )
        return plan
    conflicts, faculty = _course_dependents(config, index)
    if conflicts:
        plan.effects.append(
            f"{course.course_id} is removed from the conflict list of {_plural(len(conflicts), 'course section')}."
        )
        plan.groups.append({"title": "Conflict lists", "names": conflicts})
    if faculty:
        plan.effects.append(
            f"{course.course_id} is removed from the course preferences of {_plural(len(faculty), 'faculty member')}."
        )
        plan.groups.append({"title": "Faculty preferences", "names": faculty})
    return plan


def _build_course(config, index: int, plan: Plan):
    course_id = config.config.courses[index].course_id
    conflicts, faculty = _course_dependents(config, index)

    def mutate(draft):
        _delete_sections(draft, [index])

    notices = []
    parts = []
    if conflicts:
        parts.append(f"the conflict list of {_plural(len(conflicts), 'course section')}")
    if faculty:
        parts.append(_plural(len(faculty), "faculty course preference"))
    if parts:
        notices.append(f"Removed {course_id} from {' and '.join(parts)}.")
    return mutate, notices


# ---------------------------------------------------------------------- #
#  Class patterns
# ---------------------------------------------------------------------- #
def _pattern_at(config, index):
    patterns = config.time_slot_config.classes
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(patterns):
        raise ControllerError("That class pattern no longer exists. Refresh the page and try again.")
    return patterns[index]


def _pattern_dependents(config, index: int) -> list[tuple[int, str, object]]:
    """Course sections that would have NO enabled pattern left with their credits."""
    pattern = _pattern_at(config, index)
    if getattr(pattern, "disabled", False):
        return []
    others = [
        p for i, p in enumerate(config.time_slot_config.classes)
        if i != index and not getattr(p, "disabled", False) and p.credits == pattern.credits
    ]
    if others:
        return []
    return [(i, d, c) for i, d, c in _sections(config) if c.credits == pattern.credits]


def _usage_pattern(config, index: int) -> dict:
    dependents = _pattern_dependents(config, index)
    if not dependents:
        return {"in_use": False, "groups": []}
    return {
        "in_use": True,
        "groups": [
            {
                "chip": f"needed by {_plural(len(dependents), 'section')}",
                "tone": "info",
                "title": "Needed by",
                "names": [d for _, d, _ in dependents],
            }
        ],
    }


def _plan_pattern(config, index: int) -> Plan:
    pattern = _pattern_at(config, index)
    plan = Plan("pattern", index, f"pattern {index} ({pattern.credits} credits)")
    dependents = _pattern_dependents(config, index)
    if dependents:
        count = len(dependents)
        plan.effects.append(
            f"It is the only enabled {pattern.credits}-credit pattern, so "
            f"{_plural(count, 'course section')} could not be scheduled without it."
        )
        plan.effects.append(
            f"{'That section is' if count == 1 else 'Those sections are'} deleted along with it "
            f"(and removed from any conflict lists and faculty preferences)."
        )
        plan.groups.append({"title": "Course sections that would be deleted", "names": [d for _, d, _ in dependents]})
        plan.removes_courses = [i for i, _, _ in dependents]
    return plan


def _build_pattern(config, index: int, plan: Plan):
    doomed = list(plan.removes_courses)

    def mutate(draft):
        _delete_sections(draft, doomed)
        del draft.time_slot_config.classes[index]

    return mutate, _also_deleted_notice(config, plan)


# ---------------------------------------------------------------------- #
#  Public API
# ---------------------------------------------------------------------- #
def usage(config, kind: str, ident) -> dict:
    """The "who uses this?" summary for list pages: {"in_use", "groups"}.

    Each group is {"chip": short text, "tone", "title", "names": [...]}.
    """
    if kind in _RESOURCES:
        _resource_record(config, _RESOURCES[kind], ident)
        return _usage_resource(config, _RESOURCES[kind], ident)
    if kind == "faculty":
        _faculty_record(config, ident)
        return _usage_faculty(config, ident)
    if kind == "course":
        return _usage_course(config, ident)
    if kind == "pattern":
        return _usage_pattern(config, ident)
    raise ValueError(f"unknown kind {kind!r}")


def plan(config, kind: str, ident) -> Plan:
    """What deleting this record would do, and what the user must confirm."""
    if kind in _RESOURCES:
        return _plan_resource(config, _RESOURCES[kind], ident)
    if kind == "faculty":
        return _plan_faculty(config, ident)
    if kind == "course":
        return _plan_course(config, ident)
    if kind == "pattern":
        return _plan_pattern(config, ident)
    raise ValueError(f"unknown kind {kind!r}")


def resolve(the_plan: Plan) -> None:
    """Check the delete may go ahead. Raises ControllerError when the plan is
    blocked (for example the only room); nothing else needs confirming."""
    if the_plan.blocked:
        raise ControllerError(the_plan.blockers[0])


def build(config, kind: str, ident, the_plan: Plan):
    """Return (mutate, notices). `mutate(draft)` performs the whole cascade."""
    if kind in _RESOURCES:
        return _build_resource(config, _RESOURCES[kind], ident, the_plan)
    if kind == "faculty":
        return _build_faculty(config, ident, the_plan)
    if kind == "course":
        return _build_course(config, ident, the_plan)
    if kind == "pattern":
        return _build_pattern(config, ident, the_plan)
    raise ValueError(f"unknown kind {kind!r}")
