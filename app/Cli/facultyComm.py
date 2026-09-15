# Called from main.py per faculty subcommand:
#   python main.py faculty add     -> add_faculty()
#   python main.py faculty modify  -> modify_faculty()
#   python main.py faculty delete  -> delete_faculty()
#   python main.py faculty view    -> view_faculty()
#
# Each function loads the config, prompts the user, does one operation,
# then saves -- since argparse runs a fresh process per command, nothing
# stays in memory between calls.
#
# *** If commands.py already has shared load_config()/save_config(),
# delete the two below and use those instead so everyone reads/writes
# the same file. ***

import json
import os

# FacultyModel.Faculty.* below matches the calling convention already used
# elsewhere on the team (Faculty is a class of staticmethods -- it's never
# instantiated, every method just takes the faculty list as its first
# argument like a normal function).
import app.model.facultyModel as FacultyModel
from app.model.facultyModel import FacultyValidationError

CONFIG_PATH = "config.json"  # <-- match this to the rest of commands.py

DEFAULT_TIME_RANGE = "09:00-17:00"
DAYS = ["MON", "TUE", "WED", "THU", "FRI"]


def load_config(path=CONFIG_PATH):
    """Loads the config JSON, creating a blank skeleton if it doesn't exist."""
    if not os.path.exists(path):
        return {"config": {"rooms": [], "labs": [], "courses": [], "faculty": []}}
    with open(path, "r") as f:
        data = json.load(f)
    data.setdefault("config", {})
    data["config"].setdefault("faculty", [])
    return data


def save_config(data, path=CONFIG_PATH):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)


def daysAndTimes():
    """Asks for availability day by day. "N/A" skips the day entirely
    (unavailable); blank defaults to 09:00-17:00."""
    print("\033[31mNOTE: For the following prompts, if a faculty is available two or more different times in one day,\033[0m")
    print("\033[31mseparate the times by commas:\033[0m")

    availability = {}
    for day in DAYS:
        print(f'When are they available on {day}? (Leave blank for {DEFAULT_TIME_RANGE}, type "N/A" if not available)')
        time_input = input().lower().replace(" ", "")

        if time_input == "":
            availability[day] = [DEFAULT_TIME_RANGE]
        elif time_input == "n/a":
            continue
        else:
            availability[day] = time_input.split(",")

    return availability


def _prompt_int(prompt, default, low=None, high=None):
    """Prompts for an int; falls back to default on blank/invalid/out-of-range input."""
    print(f"{prompt} (Default is {default}):")
    raw = input().strip()
    try:
        value = int(raw)
        if low is not None and value < low:
            return default
        if high is not None and value > high:
            return default
        return value
    except ValueError:
        return default


def _prompt_preferences(label):
    """Asks for a comma-separated list of names, then a 0-10 weight for
    each. Returns {} if nothing entered."""
    print(f"What are their {label} preferences? (Separate with commas, or leave blank for none)")
    names = list(filter(None, input().lower().replace(" ", "").split(",")))
    if not names:
        return {}

    prefs = {}
    for name in names:
        print(f"Enter the {label} weight (0-10) for {name} (Default is 5, 0 means no preference):")
        raw = input().strip()
        try:
            weight = int(raw)
            if not (0 <= weight <= 10):
                weight = 5
        except ValueError:
            weight = 5
        prefs[name] = weight
    return prefs


def add_faculty():
    config = load_config()
    faculty = config["config"]["faculty"]

    print("Enter the faculty's name: ")
    faculty_name = input().strip()
    if faculty_name == "":
        print("You entered a blank name!")
        return
    if FacultyModel.Faculty.facCheck(faculty, faculty_name):
        print("Faculty is already in system!")
        return

    print('Are they full-time or adjunct? (Enter "full" or "adjunct") (Default: full)')
    full_or_part_time = input().lower().replace(" ", "")
    if full_or_part_time not in ("full", "adjunct"):
        full_or_part_time = "full"

    # full-time vs. adjunct sets the credit ceiling and course limit defaults
    if full_or_part_time == "full":
        unique_course_limit = 2
        max_teachable_credits = 12
    else:
        unique_course_limit = 1
        max_teachable_credits = 4

    min_credits = _prompt_int(
        "Enter the minimum credits a faculty can teach per semester", default=0, low=0, high=max_teachable_credits
    )
    max_credits = _prompt_int(
        "Enter the maximum credits a faculty can teach per semester",
        default=max_teachable_credits,
        low=min_credits,
        high=max_teachable_credits,
    )

    time_available = daysAndTimes()
    course_preferences = _prompt_preferences("course")
    room_preferences = _prompt_preferences("room")
    lab_preferences = _prompt_preferences("lab")

    new_faculty = {
        "name": faculty_name,
        "maximum_credits": max_credits,
        "minimum_credits": min_credits,
        "unique_course_limit": unique_course_limit,
        "times": time_available,
        "course_preferences": course_preferences,
        "room_preferences": room_preferences,
        "lab_preferences": lab_preferences,
    }

    try:
        FacultyModel.Faculty.addFaculty(faculty, new_faculty)
        save_config(config)
        print("Faculty added.")
    except FacultyValidationError as e:
        print(f"Could not add faculty: {e}")


def modify_faculty():
    config = load_config()
    faculty = config["config"]["faculty"]

    print("What is the name of the faculty would you like to edit?")
    faculty_to_edit = input().strip()
    if faculty_to_edit == "":
        print("Error! You entered nothing!")
        return
    if not FacultyModel.Faculty.facCheck(faculty, faculty_to_edit):
        print("Faculty does not exist!")
        return

    # pull the record out so we can restore it if the edit turns out invalid
    previous_faculty = FacultyModel.Faculty.removeFaculty(faculty, faculty_to_edit)

    faculty_name = previous_faculty["name"]
    unique_course_limit = previous_faculty["unique_course_limit"]
    maximum_credits = previous_faculty["maximum_credits"]
    minimum_credits = previous_faculty["minimum_credits"]
    time_available = previous_faculty["times"]
    course_preferences = previous_faculty["course_preferences"]
    room_preferences = previous_faculty["room_preferences"]
    lab_preferences = previous_faculty["lab_preferences"]

    print("What would you like to edit? Your options are:")
    print("name, availability, course preferences, credits, \nroom preferences, lab preferences (separate choices with commas)")
    things_to_edit = input().lower().replace(" ", "").split(",")

    if "name" in things_to_edit:
        print("Enter the new name for this faculty:")
        new_name = input().strip()
        if new_name and new_name != faculty_name and FacultyModel.Faculty.facCheck(faculty, new_name):
            print(f"'{new_name}' is already in use; keeping the old name.")
        elif new_name:
            faculty_name = new_name

    if "availability" in things_to_edit:
        time_available = daysAndTimes()

    if "credits" in things_to_edit:
        print('Are they full-time or adjunct? (Enter "full" or "adjunct") (Default: full)')
        response = input().lower().replace(" ", "")
        max_teachable_credits = 12 if response in ("full", "") else 4
        unique_course_limit = 2 if max_teachable_credits == 12 else 1

        minimum_credits = _prompt_int(
            "Enter the minimum credits a faculty can teach per semester", default=0, low=0, high=max_teachable_credits
        )
        maximum_credits = _prompt_int(
            "Enter the maximum credits a faculty can teach per semester",
            default=max_teachable_credits,
            low=minimum_credits,
            high=max_teachable_credits,
        )

    # only overwrite preferences if the user actually typed something new
    if "coursepreferences" in things_to_edit:
        new_prefs = _prompt_preferences("course")
        if new_prefs:
            course_preferences = new_prefs

    if "roompreferences" in things_to_edit:
        new_prefs = _prompt_preferences("room")
        if new_prefs:
            room_preferences = new_prefs

    if "labpreferences" in things_to_edit:
        new_prefs = _prompt_preferences("lab")
        if new_prefs:
            lab_preferences = new_prefs

    edited_faculty = {
        "name": faculty_name,
        "maximum_credits": maximum_credits,
        "minimum_credits": minimum_credits,
        "unique_course_limit": unique_course_limit,
        "times": time_available,
        "course_preferences": course_preferences,
        "room_preferences": room_preferences,
        "lab_preferences": lab_preferences,
    }

    try:
        FacultyModel.Faculty.addFaculty(faculty, edited_faculty)
        save_config(config)
        print("Faculty updated.")
    except FacultyValidationError as e:
        # invalid edit -> restore the original record instead of losing it
        FacultyModel.Faculty.addFaculty(faculty, previous_faculty)
        save_config(config)
        print(f"Could not save changes, restored previous version: {e}")


def delete_faculty():
    config = load_config()
    faculty = config["config"]["faculty"]

    print("What is the name of the faculty you want to remove?")
    name_to_remove = input().strip()

    if name_to_remove == "" or not FacultyModel.Faculty.facCheck(faculty, name_to_remove):
        print("Faculty does not exist!")
        return

    print("Are you sure you want to delete this faculty? This cannot be undone. (y/n)")
    remove_or_not = input().lower().strip()

    if remove_or_not in ("y", "yes"):
        FacultyModel.Faculty.removeFaculty(faculty, name_to_remove)
        save_config(config)
        print("Faculty removed.")
    else:
        print("Removal cancelled")


def view_faculty():
    """Not wired into main.py's argparse yet -- handy for testing. Add a
    `faculty view` subparser if you want it as a real command."""
    config = load_config()
    FacultyModel.Faculty.viewFaculty(config["config"]["faculty"])