"""
Tests for the Schedule Viewer's checkbox bar (Sections 16.1-16.2): in the Rooms & labs view
and the Faculty view, a bar at the top of the calendar lets you tick any number of rooms, labs
or faculty members to show only their meetings. The choice lives in the URL (?resource=...), so nothing here touches the session
except loading schedules.
"""

import pytest

from app.schedule_io import Assignment, MeetingTime
from gui.constants import VIEW_COURSES, VIEW_FACULTY, VIEW_ROOMS
from gui.controllers import schedule_filters
from gui.controllers.schedule_filters import NONE_VALUE
from gui.views import GRID_HEIGHT_REM, GRID_MAX_HEIGHT_REM, _schedule_grid
from tests.test_gui_schedule_room_view import VIEWER_URL, load, sample_schedule

ROOM_136 = 'title="Monday 09:00-09:50: Roddy 136"'
LAB_147 = 'title="Monday 10:00-11:50: Roddy 147"'
ROOM_140 = 'title="Monday 13:00-13:50: Roddy 140"'
HOGG = 'title="Monday 09:00-09:50: Hogg"'
KILLEN = 'title="Monday 10:00-11:50: Killen"'
ZOPPETTI = 'title="Monday 13:00-13:50: Zoppetti"'


def other_schedule():
    """A second schedule that uses a room and a faculty member the first one doesn't."""
    return [
        Assignment(
            "CMSC 140.01",
            "Hogg",
            "Caputo 210",
            None,
            (MeetingTime("TUE", "08:00", "08:50", 50),),
        ),
        Assignment(
            "CMSC 330.01",
            "Webster",
            "Roddy 136",
            None,
            (MeetingTime("WED", "15:00", "16:15", 75),),
        ),
    ]


def unassigned_schedule():
    return [
        Assignment(
            "CMSC 999.01", None, None, None, (MeetingTime("FRI", "09:00", "09:50", 50),)
        )
    ]


def names(group):
    return [option.label for option in group.options]


# ---------------------------------------------------------------------- #
#  Choices (pure functions)
# ---------------------------------------------------------------------- #
def test_courses_view_has_no_picker():
    assert schedule_filters.resource_groups([sample_schedule()], VIEW_COURSES) == []


def test_rooms_view_lists_rooms_and_labs_in_separate_groups():
    groups = schedule_filters.resource_groups([sample_schedule()], VIEW_ROOMS)
    assert [(g.title, names(g)) for g in groups] == [
        ("Rooms", ["Roddy 136", "Roddy 140"]),
        ("Labs", ["Roddy 147"]),
    ]


def test_faculty_view_lists_faculty_alphabetically():
    groups = schedule_filters.resource_groups([sample_schedule()], VIEW_FACULTY)
    assert [(g.title, names(g)) for g in groups] == [
        ("Faculty", ["Hogg", "Killen", "Zoppetti"])
    ]


def test_choices_come_from_every_schedule_so_paging_keeps_the_same_list():
    groups = schedule_filters.resource_groups(
        [sample_schedule(), other_schedule()], VIEW_ROOMS
    )
    assert names(groups[0]) == ["Caputo 210", "Roddy 136", "Roddy 140"]
    faculty = schedule_filters.resource_groups(
        [sample_schedule(), other_schedule()], VIEW_FACULTY
    )
    assert names(faculty[0]) == ["Hogg", "Killen", "Webster", "Zoppetti"]


def test_meeting_counts_are_for_the_schedule_on_screen():
    groups = schedule_filters.resource_groups(
        [sample_schedule(), other_schedule()],
        VIEW_ROOMS,
        current=other_schedule(),
    )
    counts = {o.label: o.meetings for o in schedule_filters.all_options(groups)}
    assert counts == {"Caputo 210": 1, "Roddy 136": 1, "Roddy 140": 0, "Roddy 147": 0}


@pytest.mark.parametrize(
    ("view", "label"),
    [(VIEW_ROOMS, "No room assigned"), (VIEW_FACULTY, "No faculty assigned")],
)
def test_unassigned_meetings_get_their_own_choice(view, label):
    groups = schedule_filters.resource_groups([unassigned_schedule()], view)
    assert [(g.title, names(g)) for g in groups] == [("Not assigned", [label])]
    assert groups[0].options[0].value == NONE_VALUE


def test_ticked_choices_are_marked_checked():
    groups = schedule_filters.resource_groups(
        [sample_schedule()], VIEW_ROOMS, selected=["Roddy 147"]
    )
    checked = [o.label for o in schedule_filters.all_options(groups) if o.checked]
    assert checked == ["Roddy 147"]


def test_selection_keeps_known_values_once_in_list_order():
    groups = schedule_filters.resource_groups([sample_schedule()], VIEW_ROOMS)
    picked = schedule_filters.selected_resources(
        ["Roddy 147", "Nowhere 1", "Roddy 136", "Roddy 147", ""], groups
    )
    assert picked == ["Roddy 136", "Roddy 147"]


# ---------------------------------------------------------------------- #
#  Calendar (pure function)
# ---------------------------------------------------------------------- #
def monday_labels(grid):
    return [m["label"] for m in grid["days"][0]["meetings"]]


def test_nothing_ticked_shows_every_meeting():
    grid = _schedule_grid(sample_schedule(), VIEW_ROOMS, [])
    assert monday_labels(grid) == ["Roddy 136", "Roddy 147", "Roddy 140"]
    assert (grid["shown"], grid["total"]) == (3, 3)


def test_ticked_rooms_and_labs_limit_the_calendar():
    grid = _schedule_grid(sample_schedule(), VIEW_ROOMS, ["Roddy 136", "Roddy 147"])
    assert monday_labels(grid) == ["Roddy 136", "Roddy 147"]
    assert (grid["shown"], grid["total"]) == (2, 3)


def test_ticked_faculty_limit_the_calendar():
    grid = _schedule_grid(sample_schedule(), VIEW_FACULTY, ["Zoppetti"])
    assert monday_labels(grid) == ["Zoppetti"]


def test_lab_filter_matches_only_the_lab_meeting_of_a_section():
    section = Assignment(
        "CMSC 162.01",
        "Killen",
        "Roddy 136",
        "Roddy 147",
        (
            MeetingTime("MON", "09:00", "09:50", 50),
            MeetingTime("TUE", "10:00", "11:50", 110, lab=True),
        ),
    )
    grid = _schedule_grid([section], VIEW_ROOMS, ["Roddy 147"])
    shown = {d["day"]: [m["label"] for m in d["meetings"]] for d in grid["days"]}
    assert shown["MON"] == [] and shown["TUE"] == ["Roddy 147"]


def test_the_time_axis_does_not_change_when_meetings_are_filtered_out():
    whole = _schedule_grid(sample_schedule(), VIEW_ROOMS)
    filtered = _schedule_grid(sample_schedule(), VIEW_ROOMS, ["Roddy 136"])
    assert filtered["hours"] == whole["hours"]
    assert filtered["height"] == whole["height"]


def mwf_day(start_hour, end_hour):
    """A long day of 50-minute MWF classes, like a real department's schedule."""
    return [
        Assignment(
            f"CMSC {100 + hour}.01",
            "Hogg",
            "Roddy 136",
            None,
            tuple(
                MeetingTime(day, f"{hour:02d}:00", f"{hour:02d}:50", 50)
                for day in ("MON", "WED", "FRI")
            ),
        )
        for hour in range(start_hour, end_hour)
    ]


def test_short_meetings_in_a_long_day_keep_their_detail_line():
    """50-minute classes from 8:00 to 20:00 used to be too short for the third line."""
    grid = _schedule_grid(mwf_day(8, 20), VIEW_COURSES)
    blocks = [m for day in grid["days"] for m in day["meetings"]]
    assert blocks and not any(m["compact"] for m in blocks)
    assert float(grid["height"].removesuffix("rem")) > GRID_HEIGHT_REM


def test_a_short_day_keeps_the_usual_height():
    grid = _schedule_grid(sample_schedule(), VIEW_COURSES)
    assert grid["height"] == f"{GRID_HEIGHT_REM:g}rem"


def test_the_calendar_never_grows_past_its_limit():
    tiny = [
        Assignment(
            "CMSC 1.01",
            None,
            None,
            None,
            (
                MeetingTime("MON", "07:00", "07:05", 5),
                MeetingTime("MON", "21:00", "21:50", 50),
            ),
        )
    ]
    grid = _schedule_grid(tiny, VIEW_COURSES)
    assert grid["height"] == f"{GRID_MAX_HEIGHT_REM:g}rem"


# ---------------------------------------------------------------------- #
#  Viewer page (Django test client)
# ---------------------------------------------------------------------- #
def test_courses_view_page_has_no_bar(client):
    load(client, sample_schedule())
    html = client.get(VIEWER_URL).content.decode()
    assert "data-resource-bar" not in html


@pytest.mark.parametrize("view", ["rooms", "faculty"])
def test_the_bar_is_always_on_the_page_in_rooms_and_faculty_views(client, view):
    load(client, sample_schedule())
    html = client.get(VIEWER_URL, {"view": view}).content.decode()
    assert "data-resource-bar" in html
    # The bar sits in the calendar card, above the calendar.
    assert html.index("data-resource-bar") < html.index('id="schedule-grid-wrap"')


def test_rooms_bar_lists_every_room_and_lab_as_a_checkbox(client):
    load(client, sample_schedule())
    html = client.get(VIEWER_URL, {"view": "rooms"}).content.decode()
    assert "<legend>Rooms</legend>" in html and "<legend>Labs</legend>" in html
    for name in ("Roddy 136", "Roddy 140", "Roddy 147"):
        assert f'type="checkbox" name="resource" value="{name}">' in html
    assert '<input type="hidden" name="view" value="rooms">' in html
    assert "Showing all 3 rooms &amp; labs." in html


def test_faculty_bar_lists_faculty_as_checkboxes(client):
    load(client, sample_schedule())
    html = client.get(VIEWER_URL, {"view": "faculty"}).content.decode()
    assert "Showing all 3 faculty." in html
    for name in ("Hogg", "Killen", "Zoppetti"):
        assert f'type="checkbox" name="resource" value="{name}">' in html


def test_the_viewer_uses_the_full_window_width(client):
    load(client, sample_schedule())
    html = client.get(VIEWER_URL).content.decode()
    assert '<main id="main" class="main--wide">' in html


def test_the_calendar_height_is_set_on_the_grid(client):
    load(client, sample_schedule())
    html = client.get(VIEWER_URL).content.decode()
    assert f"--grid-height: {GRID_HEIGHT_REM:g}rem;" in html


def test_ticking_one_room_shows_only_its_meetings(client):
    load(client, sample_schedule())
    html = client.get(
        VIEWER_URL, {"view": "rooms", "resource": "Roddy 136"}
    ).content.decode()
    assert ROOM_136 in html
    assert LAB_147 not in html and ROOM_140 not in html
    assert 'value="Roddy 136" checked>' in html
    assert (
        "Showing <strong>1</strong> of 3 meetings for 1 of 3 rooms &amp; labs." in html
    )


def test_ticking_several_shows_all_of_them(client):
    load(client, sample_schedule())
    html = client.get(
        VIEWER_URL, {"view": "rooms", "resource": ["Roddy 136", "Roddy 147"]}
    ).content.decode()
    assert ROOM_136 in html and LAB_147 in html
    assert ROOM_140 not in html


def test_ticking_faculty_shows_only_their_meetings(client):
    load(client, sample_schedule())
    html = client.get(
        VIEWER_URL, {"view": "faculty", "resource": ["Hogg", "Zoppetti"]}
    ).content.decode()
    assert HOGG in html and ZOPPETTI in html
    assert KILLEN not in html


def test_unknown_choices_are_ignored(client):
    load(client, sample_schedule())
    html = client.get(
        VIEWER_URL, {"view": "rooms", "resource": "Nowhere 1"}
    ).content.decode()
    assert ROOM_136 in html and LAB_147 in html and ROOM_140 in html
    assert "Showing all 3 rooms &amp; labs." in html


def test_choices_are_ignored_in_the_courses_view(client):
    load(client, sample_schedule())
    html = client.get(VIEWER_URL, {"resource": "Roddy 136"}).content.decode()
    assert 'title="Monday 13:00-13:50: CMSC 201.01"' in html


def test_pager_keeps_the_ticked_choices(client):
    load(client, sample_schedule(), other_schedule())
    html = client.get(
        VIEWER_URL, {"view": "rooms", "resource": ["Roddy 136", "Roddy 147"]}
    ).content.decode()
    assert (
        'href="?schedule=2&amp;view=rooms&amp;resource=Roddy+136&amp;resource=Roddy+147">Next</a>'
        in html
    )


def test_a_choice_with_no_meetings_in_this_schedule_says_so(client):
    load(client, sample_schedule(), other_schedule())
    html = client.get(
        VIEWER_URL, {"schedule": "2", "view": "rooms", "resource": "Roddy 147"}
    ).content.decode()
    assert "None of the selected rooms &amp; labs have meetings in schedule 2." in html


def test_show_all_link_clears_the_choices(client):
    load(client, sample_schedule())
    html = client.get(
        VIEWER_URL, {"view": "faculty", "resource": "Hogg"}
    ).content.decode()
    assert 'href="?schedule=1&amp;view=faculty">Show all faculty</a>' in html


def test_unassigned_choice_round_trips(client):
    load(client, unassigned_schedule())
    html = client.get(
        VIEWER_URL, {"view": "rooms", "resource": NONE_VALUE}
    ).content.decode()
    assert f'value="{NONE_VALUE}" checked>' in html
    assert (
        "Showing <strong>1</strong> of 1 meetings for 1 of 1 rooms &amp; labs." in html
    )
