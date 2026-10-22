"""
Unit tests for app/memento.py: the Memento pattern behind undo and redo.

They use the stand-in configuration in tests/fakes.py, so they need no Django
and no scheduler library.
"""

import pytest

from app.memento import (
    MEMENTO_TYPES,
    CompositeMemento,
    ConfigOriginator,
    CoursesMemento,
    FacultyMemento,
    LabsMemento,
    MementoError,
    PatternsMemento,
    RoomsMemento,
    SettingsMemento,
    TimeSlotsMemento,
)
from tests.fakes import FakeConfig, Record, course, room


def full_config():
    return FakeConfig(
        rooms=[room("R1"), room("R2")],
        labs=[room("L1")],
        courses=[course("CMSC 140", credits=4), course("CMSC 141", "01", credits=4)],
        faculty=[Record(name="Ada", maximum_credits=12)],
        classes=[Record(credits=4, meetings=[Record(day="MON", duration=50)])],
        times={"MON": ["09:00-17:00"]},
        limit=5,
        optimizer_flags=["pack_rooms"],
    )


# One way to change each kind of item, so every memento is exercised the same way.
def change_rooms(config):
    config.config.rooms.append(room("R3"))


def change_labs(config):
    config.config.labs.clear()


def change_courses(config):
    config.config.courses[0].credits = 3


def change_faculty(config):
    config.config.faculty[0].maximum_credits = 9


def change_patterns(config):
    config.time_slot_config.classes[0].meetings.append(Record(day="WED", duration=50))


def change_time_slots(config):
    config.time_slot_config.times["TUE"] = ["10:00-12:00"]


def change_settings(config):
    config.limit = 99


CHANGES = [
    (RoomsMemento, change_rooms),
    (LabsMemento, change_labs),
    (CoursesMemento, change_courses),
    (FacultyMemento, change_faculty),
    (PatternsMemento, change_patterns),
    (TimeSlotsMemento, change_time_slots),
    (SettingsMemento, change_settings),
]


def test_there_is_one_memento_for_each_kind_of_item():
    assert [kind.area for kind in MEMENTO_TYPES] == [
        "rooms",
        "labs",
        "courses",
        "faculty",
        "patterns",
        "time_slots",
        "settings",
    ]
    assert {kind for kind, _ in CHANGES} == set(MEMENTO_TYPES)


@pytest.mark.parametrize("kind, change", CHANGES)
def test_a_memento_restores_its_own_part(kind, change):
    config = full_config()
    memento = kind.capture(config)
    assert not memento.differs_from(config)
    change(config)
    assert memento.differs_from(config)
    memento.restore_to(config)
    assert config.config == full_config().config
    assert config.time_slot_config.__dict__ == full_config().time_slot_config.__dict__
    assert (config.limit, config.optimizer_flags) == (5, ["pack_rooms"])


@pytest.mark.parametrize("kind, change", CHANGES)
def test_a_memento_is_unaffected_by_later_changes_and_can_be_used_again(kind, change):
    config = full_config()
    memento = kind.capture(config)
    change(config)
    memento.restore_to(config)
    change(config)  # edit again after restoring...
    memento.restore_to(config)  # ...and the same memento still restores the original
    assert not memento.differs_from(config)


@pytest.mark.parametrize("kind, change", CHANGES)
def test_a_memento_leaves_every_other_part_alone(kind, change):
    config = full_config()
    memento = kind.capture(config)
    others = [
        (other, other.capture(config)) for other in MEMENTO_TYPES if other is not kind
    ]
    for _, other_change in CHANGES:
        other_change(config)  # change everything
    memento.restore_to(config)
    assert not memento.differs_from(config)
    for other, saved in others:
        assert saved.differs_from(config)  # the other parts were not put back


def test_a_restore_edits_lists_in_place():
    config = full_config()
    rooms_list = config.config.rooms
    memento = RoomsMemento.capture(config)
    config.config.rooms.append(room("R3"))
    memento.restore_to(config)
    assert config.config.rooms is rooms_list and len(rooms_list) == 2


# ---------------------------------------------------------------------- #
#  Describing a change in words
# ---------------------------------------------------------------------- #
def test_each_memento_describes_removed_added_and_changed_items():
    config = full_config()
    saved = RoomsMemento.capture(config)
    config.config.rooms = [room("R2", capacity=99), room("R3")]
    assert saved.describe_change(config) == [
        "Removed room R1",
        "Added room R3",
        "Changed room R2",
    ]


def test_many_changed_items_are_counted_not_listed():
    config = FakeConfig(rooms=[room(str(n)) for n in range(5)])
    saved = RoomsMemento.capture(config)
    config.config.rooms = [room(str(n), capacity=99) for n in range(5)]
    assert saved.describe_change(config) == ["Changed 5 rooms"]


def test_names_in_descriptions_fit_each_kind_of_item():
    config = full_config()
    config.config.faculty.append(Record(name="Grace", maximum_credits=1))
    config.config.faculty.append(Record(name="Alan", maximum_credits=1))
    saved = [
        FacultyMemento.capture(config),
        CoursesMemento.capture(config),
        PatternsMemento.capture(config),
        LabsMemento.capture(config),
    ]
    config.config.faculty.clear()
    config.config.courses.pop()  # CMSC 141 section 01
    config.time_slot_config.classes.clear()
    config.config.labs.clear()
    assert saved[0].describe_change(config) == ["Removed 3 faculty members"]
    assert saved[1].describe_change(config) == ["Removed course CMSC 141.01"]
    assert saved[2].describe_change(config) == [
        "Removed class pattern 4-credit pattern"
    ]
    assert saved[3].describe_change(config) == ["Removed lab L1"]


def test_equal_items_are_not_reported_as_changes():
    config = full_config()
    saved = CoursesMemento.capture(config)
    config.config.courses = [
        course("CMSC 140", credits=4),
        course("CMSC 141", "01", credits=4),
    ]
    assert saved.describe_change(config) == []
    assert not saved.differs_from(config)


def test_time_slots_and_settings_describe_themselves():
    config = full_config()
    slots, settings = TimeSlotsMemento.capture(config), SettingsMemento.capture(config)
    assert (
        slots.describe_change(config) == [] and settings.describe_change(config) == []
    )
    change_time_slots(config)
    change_settings(config)
    assert slots.describe_change(config) == ["Changed time slots"]
    assert settings.describe_change(config) == ["Changed global settings"]


def test_a_memento_has_a_readable_repr():
    assert repr(RoomsMemento.capture(full_config())) == "<RoomsMemento>"


# ---------------------------------------------------------------------- #
#  Several mementos together
# ---------------------------------------------------------------------- #
def test_a_composite_remembers_only_the_parts_asked_for():
    config = full_config()
    assert CompositeMemento.capture(config).areas == [
        kind.area for kind in MEMENTO_TYPES
    ]
    some = CompositeMemento.capture(config, ["courses", "rooms"])
    assert some.areas == ["courses", "rooms"] and len(some) == 2


def test_a_composite_keeps_only_the_parts_that_changed():
    config = full_config()
    everything = CompositeMemento.capture(config)
    change_rooms(config)
    change_courses(config)
    assert everything.changed_since(config).areas == ["rooms", "courses"]
    assert len(everything.changed_since(full_config())) == 0


def test_a_composite_describes_and_restores_all_its_parts_as_one():
    config = full_config()
    before = CompositeMemento.capture(config)
    config.config.rooms = [room("R2")]
    config.config.courses[0].credits = 3
    changed = before.changed_since(config)
    assert changed.describe_change(config) == "Removed room R1; Changed course CMSC 140"
    changed.restore_to(config)
    assert config.config == full_config().config


def test_describing_no_change_gives_an_empty_string():
    config = full_config()
    assert CompositeMemento.capture(config).describe_change(config) == ""


# ---------------------------------------------------------------------- #
#  The originator
# ---------------------------------------------------------------------- #
def test_the_originator_saves_and_restores_the_configuration():
    config = full_config()
    originator = ConfigOriginator(config)
    memento = originator.create_memento()
    change_rooms(config)
    change_settings(config)
    originator.restore(memento)
    assert [item.name for item in config.config.rooms] == ["R1", "R2"]
    assert config.limit == 5


def test_the_originator_can_save_just_some_parts():
    config = full_config()
    memento = ConfigOriginator(config).create_memento(["settings"])
    assert memento.areas == ["settings"]


def test_a_restore_that_is_refused_changes_nothing():
    config = full_config()
    originator = ConfigOriginator(config)
    memento = originator.create_memento(["rooms"])
    change_rooms(config)
    config.refuse_edits = True
    with pytest.raises(MementoError, match="nothing was changed"):
        originator.restore(memento)
    assert [item.name for item in config.config.rooms] == ["R1", "R2", "R3"]


def test_a_part_the_configuration_does_not_have_is_skipped():
    config = FakeConfig(rooms=[room("R1")])
    del config.limit  # a trimmed-down configuration, as some unit tests use
    del config.optimizer_flags
    memento = CompositeMemento.capture(config)
    assert "settings" not in memento.areas and "rooms" in memento.areas
    assert SettingsMemento.exists_in(full_config())
    assert not SettingsMemento.exists_in(config)
