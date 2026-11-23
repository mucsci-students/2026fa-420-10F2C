"""
Tests for locking, unlocking and listing sections through the AI chat (gui/ai/locks.py).

The tools are called the way the AI calls them, against the real session, controllers and pages. The
schedules are plain records (no solver runs), like tests/test_lock_controller.py. The AI itself is
replaced by a scripted runner that calls the tools a model would have chosen; everything after that
is real. No AI, no key and no network are used.

    ToolBox(request).call("lock_sections", {"sections": ["CMSC 141.01"]})

What these cover
  * lock and unlock through the chat: the confirmation, the Schedule Viewer's banner and the Schedule
    Generator's table, and the configuration left exactly as it was (never "unsaved")
  * the list of locked sections is the Generator's list, and says so plainly when nothing is locked
  * a section that is not in the viewed schedule, an ambiguous name, a clash, no schedules at all:
    clear messages, and no lock created or changed (all or nothing)
  * which schedule is used: the viewed one, an explicit one, or schedule 1 with a note
  * the extras: several sections in one call, one instructor's sections, unlock all, "lock only",
    reading the schedule first, and several actions in one message
  * the page behind the chat is refreshed after a real lock change (and only then)
  * the tools are classified, described to the model and mentioned in the capability list
"""

from pathlib import Path

import pytest

from app.schedule_io import Assignment, MeetingTime
from gui import session_store
from gui.ai import clarify, service
from gui.ai import locks as ai_locks
from gui.ai.prompt import BASE_PROMPT, CAPABILITIES
from gui.ai.tools import TOOLS_BY_NAME, ToolBox
from gui.controllers import schedule_controller

ROOT = Path(__file__).resolve().parent.parent
ASK_URL = "/assistant/ask/"
VIEWER_URL = "/schedules/"
GENERATOR_URL = "/generate/"

LOCK_TOOL_NAMES = (
    "lock_sections",
    "unlock_sections",
    "view_locked_sections",
    "unlock_all_sections",
    "lock_faculty_sections",
    "unlock_faculty_sections",
)


def section(course, faculty, room, day, start="09:00", end="09:50"):
    return Assignment(course, faculty, room, None, (MeetingTime(day, start, end, 50),))


A1 = section("CMSC 141.01", "Hogg", "Roddy 136", "MON")
A2 = section("CMSC 141.02", "Hogg", "Roddy 140", "TUE", "10:00", "10:50")
B1 = section("CMSC 142.01", "Barr", "Roddy 147", "WED")
NOBODY = section("CMSC 150.01", None, "Roddy 150", "FRI")
A1_MOVED = section("CMSC 141.01", "Hogg", "Roddy 136", "THU")  # same section, elsewhere
B1_CLASH = section(
    "CMSC 142.01", "Barr", "Roddy 136", "MON"
)  # takes A1's room and time

SCHEDULE_1 = [A1, A2, B1, NOBODY]
SCHEDULE_2 = [A1_MOVED, A2, B1]
SCHEDULE_3 = [B1_CLASH]
SCHEDULES = [SCHEDULE_1, SCHEDULE_2, SCHEDULE_3]


class FakeRequest:
    """Enough of a Django request for get_session(): just a session dict."""

    def __init__(self):
        self.session = {}


@pytest.fixture(autouse=True)
def fresh_session_store():
    session_store._SESSIONS.clear()
    yield
    session_store._SESSIONS.clear()


@pytest.fixture
def request_():
    return FakeRequest()


@pytest.fixture
def bare(request_):
    """This browser's session, with the example configuration and NO schedules."""
    return session_store.get_session(request_)


@pytest.fixture
def session(bare):
    bare.set_schedules(SCHEDULES)
    return bare


@pytest.fixture
def box(request_, session):
    return ToolBox(request_)


def view(request_, number):
    """The Schedule Viewer is showing schedule `number` (what chat.js sends)."""
    ai_locks.note_viewed_schedule(request_, str(number))


def lock(box, *sections, **extra):
    return box.call("lock_sections", {"sections": list(sections), **extra})


def unlock(box, *sections):
    return box.call("unlock_sections", {"sections": list(sections)})


# ---------------------------------------------------------------------- #
#  Locking one section
# ---------------------------------------------------------------------- #
def test_locking_confirms_and_changes_nothing_but_the_locks(box, session):
    before = session.dumps()
    version = session.history.version

    result = lock(box, "CMSC 141.01")

    assert result.ok and not result.changed and not result.write
    assert result.message.startswith('Locked "CMSC 141.01".')
    assert "stays exactly as placed" in result.message
    assert "The configuration was not changed." in result.message
    assert session.locks.sections() == ["CMSC 141.01"]
    assert session.locks.get("CMSC 141.01").assignment == A1
    assert session.locks.get("CMSC 141.01").source == 1
    # Locks are not configuration: nothing to save, nothing to undo.
    assert session.dumps() == before and session.dirty is False
    assert session.history.version == version
    assert "not yet saved" not in service.compose(box.results).message


def test_a_lock_change_is_reported_so_the_page_is_redrawn(box):
    result = lock(box, "CMSC 141.01")
    assert result.locks_changed and not result.schedules_changed
    assert service.compose(box.results).refresh is True


def test_locking_the_same_section_again_changes_nothing_and_does_not_refresh(
    box, session
):
    lock(box, "CMSC 141.01")
    version = session.locks.version
    again = lock(box, "CMSC 141.01")
    assert again.ok and "already locked exactly like this" in again.message
    assert session.locks.version == version
    assert not again.locks_changed
    assert service.compose([again]).refresh is False


def test_part_of_a_name_is_enough(box, session):
    assert lock(box, "141.02").ok
    assert lock(box, "cmsc142.01").ok
    assert session.locks.sections() == ["CMSC 141.02", "CMSC 142.01"]


def test_a_single_string_instead_of_a_list_is_accepted(box, session):
    result = box.call("lock_sections", {"sections": "CMSC 141.01"})
    assert result.ok and session.locks.sections() == ["CMSC 141.01"]


def test_several_sections_in_one_call(box, session):
    result = lock(
        box, "CMSC 141.01", "CMSC 142.01", "CMSC 141.01"
    )  # a repeat is ignored
    assert result.ok
    assert result.message.startswith('Locked "CMSC 141.01" and "CMSC 142.01".')
    assert session.locks.sections() == ["CMSC 141.01", "CMSC 142.01"]


def test_nothing_named_asks_for_a_section_and_creates_no_lock(box, session):
    result = lock(box)
    assert not result.ok and "Say which section to lock" in result.message
    assert len(session.locks) == 0 and not result.locks_changed


# ---------------------------------------------------------------------- #
#  Which schedule
# ---------------------------------------------------------------------- #
def test_without_a_viewer_schedule_the_first_is_used_and_the_reply_says_so(box):
    result = lock(box, "CMSC 141.01")
    assert result.message.endswith(
        "I used schedule 1 because no schedule is open in the Schedule Viewer."
    )


def test_the_schedule_open_in_the_viewer_is_the_one_locked_from(box, request_, session):
    view(request_, 2)
    result = lock(box, "CMSC 141.01")
    assert result.ok and "I used schedule" not in result.message
    assert session.locks.get("CMSC 141.01").assignment == A1_MOVED
    assert session.locks.get("CMSC 141.01").source == 2


def test_a_schedule_the_user_names_wins_over_the_viewer(box, request_, session):
    view(request_, 2)
    assert lock(box, "CMSC 141.01", schedule=1).ok
    assert session.locks.get("CMSC 141.01").assignment == A1


def test_a_viewer_number_out_of_range_falls_back_to_the_first_like_the_viewer(
    box, request_, session
):
    view(request_, 9)
    result = lock(box, "CMSC 141.01")
    assert result.ok and "I used schedule" not in result.message
    assert session.locks.get("CMSC 141.01").source == 1


def test_a_schedule_that_does_not_exist_is_refused(box, session):
    result = lock(box, "CMSC 141.01", schedule=7)
    assert not result.ok and "Schedule 7 doesn't exist" in result.message
    assert len(session.locks) == 0


@pytest.mark.parametrize(
    "raw, expected",
    [("2", 2), (" 3 ", 3), ("", None), ("abc", None), ("-1", None), ("2.5", None)]
    + [("²", None), ("1" * 12, None), (None, None)],
)
def test_the_viewer_schedule_number_is_read_defensively(request_, raw, expected):
    ai_locks.note_viewed_schedule(request_, raw)
    assert getattr(request_, ai_locks.VIEWED_SCHEDULE_ATTR) == expected


def test_with_no_schedules_the_reply_says_so(request_, bare):
    box = ToolBox(request_)
    result = lock(box, "CMSC 141.01")
    assert not result.ok
    assert result.message == schedule_controller.NO_SCHEDULES_MESSAGE
    assert len(bare.locks) == 0


# ---------------------------------------------------------------------- #
#  Invalid requests change nothing
# ---------------------------------------------------------------------- #
def test_a_section_that_is_not_in_the_viewed_schedule_is_explained(
    box, request_, session
):
    view(request_, 3)  # schedule 3 holds only CMSC 142.01
    result = lock(box, "CMSC 141.01")
    assert not result.ok
    assert (
        'couldn\'t find a section called "CMSC 141.01" in schedule 3' in result.message
    )
    assert "Nothing was locked" in result.message
    assert len(session.locks) == 0 and not result.locks_changed


def test_an_unknown_section_creates_nothing_and_leaves_existing_locks_alone(
    box, session
):
    lock(box, "CMSC 141.01")
    version, before = session.locks.version, session.dumps()

    result = lock(box, "CMSC 999.01")

    assert not result.ok
    assert (
        'couldn\'t find a section called "CMSC 999.01" in schedule 1' in result.message
    )
    assert "existing locks and the configuration were not changed" in result.message
    assert session.locks.sections() == ["CMSC 141.01"]
    assert session.locks.get("CMSC 141.01").assignment == A1
    assert session.locks.version == version and session.dumps() == before
    assert not result.locks_changed and service.compose([result]).refresh is False


def test_one_bad_name_in_a_batch_locks_none_of_them(box, session):
    result = lock(box, "CMSC 141.01", "CMSC 999.01")
    assert not result.ok and '"CMSC 999.01"' in result.message
    assert len(session.locks) == 0


def test_several_unknown_names_are_all_listed(box, session):
    result = lock(box, "CMSC 998.01", "CMSC 999.01")
    assert not result.ok
    assert '"CMSC 998.01" and "CMSC 999.01"' in result.message
    assert len(session.locks) == 0


def test_a_name_that_fits_two_sections_is_asked_about_not_guessed(box, session):
    result = lock(box, "CMSC 141")
    assert not result.ok
    assert "could mean CMSC 141.01, CMSC 141.02" in result.message
    assert "Nothing was locked" in result.message
    assert len(session.locks) == 0
    assert clarify.current(session) is None  # a plain failure: no half-remembered batch


def test_a_lock_that_clashes_with_a_held_one_is_refused(box, request_, session):
    lock(box, "CMSC 141.01")  # schedule 1: Roddy 136, Monday 09:00
    view(request_, 3)
    result = lock(box, "CMSC 142.01")  # schedule 3 puts it in Roddy 136, Monday 09:00
    assert not result.ok
    assert "same room" in result.message and "Nothing was locked" in result.message
    assert session.locks.sections() == ["CMSC 141.01"]


def test_replacing_the_other_locks_lets_a_clashing_section_in(box, request_, session):
    lock(box, "CMSC 141.01")
    view(request_, 3)
    result = lock(box, "CMSC 142.01", replace_existing_locks=True)
    assert result.ok and "only locks" in result.message
    assert "CMSC 141.01" in result.message  # named as unlocked
    assert session.locks.sections() == ["CMSC 142.01"]
    assert session.locks.get("CMSC 142.01").assignment == B1_CLASH


def test_a_refused_replace_keeps_every_existing_lock(box, request_, session):
    lock(box, "CMSC 141.01", "CMSC 142.01")
    result = lock(box, "CMSC 999.01", replace_existing_locks=True)
    assert not result.ok
    assert session.locks.sections() == ["CMSC 141.01", "CMSC 142.01"]


def test_relocking_from_another_schedule_says_so(box, request_, session):
    lock(box, "CMSC 141.01")
    view(request_, 2)
    result = lock(box, "CMSC 141.01")
    assert result.ok and "instead of the earlier lock" in result.message
    assert result.locks_changed
    assert session.locks.get("CMSC 141.01").assignment == A1_MOVED


# ---------------------------------------------------------------------- #
#  Unlocking
# ---------------------------------------------------------------------- #
def test_unlocking_confirms_and_the_section_is_free_again(box, session):
    lock(box, "CMSC 141.01", "CMSC 142.01")
    before = session.dumps()

    result = unlock(box, "cmsc 141.01")

    assert result.ok and not result.changed
    assert result.message.startswith('Unlocked "CMSC 141.01".')
    assert "can change the next time you generate" in result.message
    assert result.locks_changed
    assert session.locks.sections() == ["CMSC 142.01"]
    assert session.dumps() == before and session.dirty is False


def test_unlocking_a_section_that_is_not_locked_changes_nothing(box, session):
    lock(box, "CMSC 141.01")
    version = session.locks.version
    result = unlock(box, "CMSC 150.01")  # a real section, but not locked
    assert not result.ok
    assert (
        'couldn\'t find a section called "CMSC 150.01" among the locked sections'
        in (result.message)
    )
    assert "Locked sections: CMSC 141.01" in result.message
    assert session.locks.sections() == ["CMSC 141.01"]
    assert session.locks.version == version and not result.locks_changed


def test_one_bad_name_when_unlocking_unlocks_none_of_them(box, session):
    lock(box, "CMSC 141.01", "CMSC 142.01")
    result = unlock(box, "CMSC 141.01", "CMSC 999.01")
    assert not result.ok
    assert session.locks.sections() == ["CMSC 141.01", "CMSC 142.01"]


def test_unlocking_with_nothing_locked_says_so_and_is_not_an_error(box, session):
    result = unlock(box, "CMSC 141.01")
    assert result.ok and "No sections are currently locked" in result.message
    assert "nothing to unlock" in result.message and not result.locks_changed


def test_unlock_asks_for_a_section_when_none_is_named(box, session):
    lock(box, "CMSC 141.01")
    result = unlock(box)
    assert not result.ok and "Say which section to unlock" in result.message
    assert session.locks.sections() == ["CMSC 141.01"]


# ---------------------------------------------------------------------- #
#  Viewing the locks
# ---------------------------------------------------------------------- #
def test_with_nothing_locked_the_list_says_so_clearly(box):
    result = box.call("view_locked_sections")
    assert result.ok and result.final
    assert result.message.startswith("No sections are currently locked.")
    assert not result.locks_changed


def test_the_list_shows_who_where_when_and_which_schedule(box, request_, session):
    lock(box, "CMSC 141.01")
    view(request_, 2)
    lock(box, "CMSC 142.01")

    message = box.call("view_locked_sections").message

    assert message.startswith("2 sections are locked.")
    assert "- CMSC 141.01: Hogg, Roddy 136, Mon 09:00" in message
    assert "(locked from schedule 1)" in message
    assert "- CMSC 142.01: Barr, Roddy 147, Wed 09:00" in message
    assert "(locked from schedule 2)" in message
    assert "CMSC 141.02" not in message


def test_the_list_follows_the_viewers_clock(box, request_, session):
    lock(box, "CMSC 141.01")
    request_.session[ai_locks.TIME_FORMAT_KEY] = "12h"
    assert "AM" in box.call("view_locked_sections").message
    request_.session[ai_locks.TIME_FORMAT_KEY] = "24h"
    assert "AM" not in box.call("view_locked_sections").message


def test_the_clock_key_is_the_one_the_viewer_uses():
    from gui.views import TIME_FORMAT_KEY

    assert ai_locks.TIME_FORMAT_KEY == TIME_FORMAT_KEY


def test_after_unlocking_everything_the_list_says_none_are_locked(box, session):
    lock(box, "CMSC 141.01", "CMSC 142.01")
    assert box.call("view_locked_sections").message.startswith("2 sections")
    cleared = box.call("unlock_all_sections")
    assert cleared.ok and "Unlocked all 2 locked sections" in cleared.message
    assert cleared.locks_changed and len(session.locks) == 0
    assert box.call("view_locked_sections").message.startswith(
        "No sections are currently locked."
    )


def test_unlock_all_with_nothing_locked_changes_nothing(box):
    result = box.call("unlock_all_sections")
    assert result.ok and "nothing to unlock" in result.message
    assert not result.locks_changed


# ---------------------------------------------------------------------- #
#  One instructor's sections, and reading the schedule first
# ---------------------------------------------------------------------- #
def test_locking_everything_one_instructor_teaches(box, session):
    result = box.call("lock_faculty_sections", {"faculty": "hogg"})
    assert result.ok and "taught by Hogg" in result.message
    assert session.locks.sections() == ["CMSC 141.01", "CMSC 141.02"]
    assert "The configuration was not changed." in result.message
    assert result.locks_changed


def test_an_unknown_instructor_locks_nothing(box, session):
    result = box.call("lock_faculty_sections", {"faculty": "Nobody"})
    assert not result.ok
    assert 'couldn\'t find an instructor called "Nobody"' in result.message
    assert "Instructors in schedule 1: Barr, Hogg" in result.message
    assert len(session.locks) == 0


def test_unlocking_everything_one_instructor_teaches(box, session):
    lock(box, "CMSC 141.01", "CMSC 141.02", "CMSC 142.01")
    result = box.call("unlock_faculty_sections", {"faculty": "Hogg"})
    assert result.ok and "Unlocked 2 sections taught by Hogg" in result.message
    assert session.locks.sections() == ["CMSC 142.01"]


def test_unlocking_an_instructor_with_no_locks_changes_nothing(box, session):
    lock(box, "CMSC 141.01")
    result = box.call("unlock_faculty_sections", {"faculty": "Barr"})
    assert not result.ok and "among the locked sections" in result.message
    assert session.locks.sections() == ["CMSC 141.01"]


def test_the_schedule_can_be_read_before_acting(box, request_, session):
    lock(box, "CMSC 141.01")
    view(request_, 2)
    tool = TOOLS_BY_NAME["list_schedule_sections"]
    assert not tool.final  # a lookup: only the AI reads it

    result = box.call("list_schedule_sections")

    assert result.ok and not result.final and not result.locks_changed
    assert result.message.startswith("Schedule 2 of 3 has 3 sections:")
    assert "[locked, but placed differently in this schedule]" in result.message
    assert "- CMSC 142.01: Barr, Roddy 147, Wed 09:00" in result.message
    free = [line for line in result.message.splitlines() if "CMSC 142.01" in line]
    assert "[locked" not in free[0]


def test_a_section_with_no_room_or_instructor_is_listed_plainly(box):
    message = box.call("list_schedule_sections", {"schedule": 1}).message
    assert "- CMSC 150.01: No faculty assigned, Roddy 150, Fri 09:00" in message


# ---------------------------------------------------------------------- #
#  Locks and a request that is waiting for details
# ---------------------------------------------------------------------- #
def test_locking_neither_waits_for_nor_drops_a_pending_request(box, session):
    asked = box.call("add_room", {"name": "RODDY150"})  # the capacity is still missing
    assert asked.questions
    held = clarify.current(session)
    assert held is not None

    result = lock(box, "CMSC 141.01")

    assert result.ok and session.locks.sections() == ["CMSC 141.01"]
    assert clarify.current(session) is held


# ---------------------------------------------------------------------- #
#  The whole chat: endpoint, refresh, the viewer page and the generator page
# ---------------------------------------------------------------------- #
SCRIPT = {
    "lock 141.01": [("lock_sections", {"sections": ["CMSC 141.01"]})],
    "lock two": [("lock_sections", {"sections": ["CMSC 141.01", "CMSC 142.01"]})],
    "lock 999": [("lock_sections", {"sections": ["CMSC 999.01"]})],
    "unlock 141.01": [("unlock_sections", {"sections": ["CMSC 141.01"]})],
    "which are locked": [("view_locked_sections", {})],
    "unlock all": [("unlock_all_sections", {})],
    "swap": [
        ("unlock_sections", {"sections": ["CMSC 141.01"]}),
        ("lock_faculty_sections", {"faculty": "Barr"}),
    ],
    "look then lock": [
        ("list_schedule_sections", {}),
        ("lock_sections", {"sections": ["CMSC 141.02"]}),
    ],
    "lock then show": [
        ("lock_sections", {"sections": ["CMSC 141.01"]}),
        ("view_locked_sections", {}),
    ],
}


class FakeRunner:
    """Stands in for the AI: calls the scripted tools for each request."""

    def run(self, text, toolbox):
        for name, arguments in SCRIPT[text]:
            toolbox.call(name, arguments)
        return ""


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(service, "get_runner", lambda: FakeRunner())


def ask(client, text, schedule=None):
    data = {"message": text}
    if schedule is not None:
        data["schedule"] = str(schedule)
    response = client.post(ASK_URL, data)
    return response.status_code, response.json()


def open_browser(client):
    """Start this browser's session (the viewer does) and give it the three schedules."""
    client.get(VIEWER_URL)
    browser = next(iter(session_store._SESSIONS.values()))
    browser.set_schedules(SCHEDULES)
    return browser


def page(client, url):
    return client.get(url).content.decode()


def test_a_lock_made_in_the_chat_shows_on_the_viewer_and_the_generator(client, fake):
    browser = open_browser(client)
    before = browser.dumps()

    status, body = ask(client, "lock 141.01", schedule=1)

    assert status == 200 and body["ok"]
    assert body["reply"].startswith('Locked "CMSC 141.01".')
    assert body["refresh"] is True  # the page behind the chat is redrawn
    assert body["changed"] is False and body["dirty"] is False
    assert "1 section locked." in page(client, VIEWER_URL + "?schedule=1")
    assert '<th scope="row">CMSC 141.01</th>' in page(client, GENERATOR_URL)
    assert browser.dumps() == before and browser.dirty is False


def test_an_unlock_made_in_the_chat_updates_both_pages(client, fake):
    open_browser(client)
    ask(client, "lock 141.01", schedule=1)

    status, body = ask(client, "unlock 141.01", schedule=1)

    assert status == 200 and body["ok"] and body["refresh"] is True
    assert body["reply"].startswith('Unlocked "CMSC 141.01".')
    assert "1 section locked." not in page(client, VIEWER_URL + "?schedule=1")
    assert '<th scope="row">CMSC 141.01</th>' not in page(client, GENERATOR_URL)


def test_the_chat_lists_the_same_sections_the_generator_shows(client, fake):
    open_browser(client)
    ask(client, "lock two", schedule=1)

    _, body = ask(client, "which are locked", schedule=1)
    generator = page(client, GENERATOR_URL)

    assert body["ok"] and body["refresh"] is False  # looking changes nothing
    for name in ("CMSC 141.01", "CMSC 142.01"):
        assert name in body["reply"]
        assert f'<th scope="row">{name}</th>' in generator
    for name in ("CMSC 141.02", "CMSC 150.01"):
        assert name not in body["reply"]
        assert f'<th scope="row">{name}</th>' not in generator


def test_after_clearing_the_list_says_none_are_locked_and_the_generator_agrees(
    client, fake
):
    open_browser(client)
    ask(client, "lock two", schedule=1)
    _, cleared = ask(client, "unlock all", schedule=1)
    _, body = ask(client, "which are locked", schedule=1)

    assert cleared["refresh"] is True
    assert body["reply"].startswith("No sections are currently locked.")
    assert "Nothing is locked" in page(client, GENERATOR_URL)


def test_a_failed_lock_in_the_chat_changes_nothing_and_does_not_refresh(client, fake):
    browser = open_browser(client)
    ask(client, "lock 141.01", schedule=1)
    before, version = browser.dumps(), browser.locks.version

    status, body = ask(client, "lock 999", schedule=1)

    assert status == 200 and body["ok"] is False
    assert 'couldn\'t find a section called "CMSC 999.01"' in body["reply"]
    assert body["refresh"] is False and body["changed"] is False
    assert browser.locks.sections() == ["CMSC 141.01"]
    assert browser.locks.version == version and browser.dumps() == before


def test_the_schedule_the_viewer_sent_is_the_one_locked_from(client, fake):
    browser = open_browser(client)
    _, body = ask(client, "lock 141.01", schedule=2)
    assert body["ok"] and "I used schedule" not in body["reply"]
    assert browser.locks.get("CMSC 141.01").assignment == A1_MOVED
    assert browser.locks.get("CMSC 141.01").source == 2


def test_without_a_viewer_schedule_the_chat_uses_schedule_1_and_says_so(client, fake):
    browser = open_browser(client)
    _, body = ask(client, "lock 141.01")  # sent from a page that is not the viewer
    assert body["ok"] and "I used schedule 1" in body["reply"]
    assert browser.locks.get("CMSC 141.01").source == 1


def test_several_actions_in_one_message_are_all_carried_out_in_order(client, fake):
    browser = open_browser(client)
    browser.locks.lock(A1, 1)

    _, body = ask(client, "swap", schedule=1)

    assert body["ok"] and body["refresh"] is True
    assert 'Unlocked "CMSC 141.01"' in body["reply"]
    assert "taught by Barr" in body["reply"]
    assert browser.locks.sections() == ["CMSC 142.01"]


def test_reading_the_schedule_first_shows_only_the_action_to_the_user(client, fake):
    browser = open_browser(client)
    _, body = ask(client, "look then lock", schedule=1)
    assert body["ok"] and body["reply"].startswith('Locked "CMSC 141.02".')
    assert "Schedule 1 of 3 has" not in body["reply"]  # the lookup is for the AI only
    assert browser.locks.sections() == ["CMSC 141.02"]


def test_a_lock_and_a_list_in_one_message(client, fake):
    open_browser(client)
    _, body = ask(client, "lock then show", schedule=1)
    assert body["ok"]
    assert 'Locked "CMSC 141.01".' in body["reply"]
    assert "1 section is locked." in body["reply"]


# ---------------------------------------------------------------------- #
#  The tools are classified, described and mentioned
# ---------------------------------------------------------------------- #
def test_every_lock_tool_is_registered_final_and_not_a_configuration_change():
    for name in LOCK_TOOL_NAMES:
        tool = TOOLS_BY_NAME[name]
        assert tool.final and not tool.write and not tool.acts_on_state, name
        assert tool.description.strip() and not tool.needs_config, name
    lookup = TOOLS_BY_NAME["list_schedule_sections"]
    assert not lookup.final and not lookup.write and lookup.name.startswith("list_")


def test_the_model_is_told_about_every_lock_tool():
    for name in (*LOCK_TOOL_NAMES, "list_schedule_sections"):
        assert name in BASE_PROMPT, name
    assert "replace_existing_locks" in BASE_PROMPT
    assert "never need saving" in BASE_PROMPT
    text = CAPABILITIES.lower()
    assert "lock sections" in text and "never change" in text


def test_chat_js_sends_the_schedule_the_viewer_is_showing():
    source = (ROOT / "gui/static/gui/js/chat.js").read_text(encoding="utf-8")
    assert "function viewedSchedule()" in source
    assert 'data.set("schedule", viewed)' in source
    assert "window.location.pathname !== viewerUrl" in source


# ---------------------------------------------------------------------- #
#  "Lock X and generate 5 schedules": both halves, whatever the AI called
# ---------------------------------------------------------------------- #
class StubBox:
    """Just enough of a ToolBox for the safety net: earlier results, and a record of what it calls."""

    def __init__(self, *results):
        self.results = list(results)
        self.called = []

    def call(self, name, arguments=None):
        self.called.append((name, arguments))


def done(tool, ok=True):
    from gui.ai.base import ToolResult

    return ToolResult(tool, ok, "message")


ASKS_BOTH = "Can you lock cmsc 152.01 and generate 5 new schedules?"


@pytest.mark.parametrize(
    "text, arguments",
    [
        (ASKS_BOTH, {"limit": 5}),
        ("lock 141.01 and then regenerate", {}),
        ("Lock it, then generate", {}),
        ("lock CMSC 141.01 and make me three new schedules", {"limit": 3}),
        ("keep that one and run a new schedule please", {}),
        ("LOCK 141.01 AND GENERATE 12 SCHEDULES", {"limit": 12}),
    ],
)
def test_the_safety_net_shows_the_generation_settings_when_the_ai_only_locked(
    text, arguments
):
    box = StubBox(done("lock_sections"))
    assert ai_locks.finish_generation_request(text, box) is True
    assert box.called == [("prepare_schedule_generation", arguments)]


@pytest.mark.parametrize("tool", sorted(ai_locks._LOCK_CHANGING))
def test_every_lock_tool_triggers_the_safety_net(tool):
    box = StubBox(done(tool))
    assert ai_locks.finish_generation_request(ASKS_BOTH, box) is True


@pytest.mark.parametrize(
    "text",
    [
        "lock cmsc 152.01 so I can generate later",
        "lock 141.01, don't generate yet",
        "lock 141.01 and I will generate after lunch",
        "lock 141.01 but do not generate anything",
        "lock 141.01 before generating",
        "lock 141.01",
        "lock 141.01 and show me what is locked",
        "",
    ],
)
def test_the_safety_net_stays_out_when_generating_is_not_asked_or_is_postponed(text):
    box = StubBox(done("lock_sections"))
    assert ai_locks.finish_generation_request(text, box) is False
    assert box.called == []


def test_a_failed_lock_never_starts_the_generation_review():
    box = StubBox(done("lock_sections", ok=False))
    assert ai_locks.finish_generation_request(ASKS_BOTH, box) is False
    box = StubBox(done("lock_sections"), done("unlock_sections", ok=False))
    assert ai_locks.finish_generation_request(ASKS_BOTH, box) is False
    assert box.called == []


@pytest.mark.parametrize(
    "tool",
    [
        "prepare_schedule_generation",
        "confirm_schedule_generation",
        "cancel_schedule_generation",
    ],
)
def test_the_safety_net_does_nothing_when_the_ai_already_handled_generation(tool):
    box = StubBox(done("lock_sections"), done(tool))
    assert ai_locks.finish_generation_request(ASKS_BOTH, box) is False
    assert box.called == []


def test_the_safety_net_needs_a_lock_change_that_really_ran():
    assert ai_locks.finish_generation_request(ASKS_BOTH, StubBox()) is False
    only_looked = StubBox(done("view_locked_sections"), done("list_schedule_sections"))
    assert ai_locks.finish_generation_request(ASKS_BOTH, only_looked) is False
    assert only_looked.called == []


class LockOnlyRunner:
    """An AI that makes the mistake: it only locks, whatever else the message asked."""

    def run(self, text, toolbox):
        toolbox.call("lock_sections", {"sections": ["CMSC 141.01"]})
        return ""


class LockAndPrepareRunner:
    """An AI that does it right: both calls, in order."""

    def run(self, text, toolbox):
        toolbox.call("lock_sections", {"sections": ["CMSC 141.01"]})
        toolbox.call("prepare_schedule_generation", {"limit": 5})
        return ""


def test_lock_and_generate_gives_both_answers_even_when_the_ai_only_locks(
    client, monkeypatch
):
    from gui.ai.generation import GO_AHEAD

    browser = open_browser(client)
    monkeypatch.setattr(service, "get_runner", lambda: LockOnlyRunner())

    status, body = ask(client, ASKS_BOTH, schedule=1)

    assert status == 200 and body["ok"]
    assert body["reply"].startswith('Locked "CMSC 141.01".')
    assert "Ready to generate schedules" in body["reply"]
    assert "Generation limit: 5" in body["reply"]
    assert "CMSC 141.01" in body["reply"].split("Ready to generate schedules")[1]
    assert GO_AHEAD in body["suggestions"]  # the user agrees in the next message
    assert body["refresh"] is True
    assert browser.locks.sections() == ["CMSC 141.01"]
    assert "1 section locked." in page(client, VIEWER_URL + "?schedule=1")


def test_lock_and_generate_is_not_doubled_when_the_ai_does_both(client, monkeypatch):
    open_browser(client)
    monkeypatch.setattr(service, "get_runner", lambda: LockAndPrepareRunner())
    _, body = ask(client, ASKS_BOTH, schedule=1)
    assert body["reply"].count("Ready to generate schedules") == 1


def test_lock_and_wait_is_left_alone(client, monkeypatch):
    browser = open_browser(client)
    monkeypatch.setattr(service, "get_runner", lambda: LockOnlyRunner())
    _, body = ask(client, "lock 141.01, I will generate later", schedule=1)
    assert body["reply"].startswith('Locked "CMSC 141.01".')
    assert "Ready to generate schedules" not in body["reply"]
    assert browser.locks.sections() == ["CMSC 141.01"]


def test_the_prompt_and_every_lock_tool_say_that_lock_plus_generate_is_two_calls():
    assert "TWO TOOL CALLS, AND BOTH ARE REQUIRED" in BASE_PROMPT
    assert "SAME response" in BASE_PROMPT and "silently drops" in BASE_PROMPT
    for name in ai_locks._LOCK_CHANGING:
        description = TOOLS_BY_NAME[name].description
        assert "prepare_schedule_generation" in description, name
        assert "SAME response" in description, name
