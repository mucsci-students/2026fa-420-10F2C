import argparse
from commands import *


def main():
    parser = argparse.ArgumentParser(
        description="Course scheduling configuration tool"
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True
    )

    # Faculty commands
    faculty_parser = subparsers.add_parser("faculty")
    faculty_subparsers = faculty_parser.add_subparsers(
        dest="action",
        required=True
    )

    faculty_subparsers.add_parser("add")
    faculty_subparsers.add_parser("modify")
    faculty_subparsers.add_parser("delete")

    # Course commands
    course_parser = subparsers.add_parser("course")
    course_subparsers = course_parser.add_subparsers(
        dest="action",
        required=True
    )

    course_subparsers.add_parser("add")
    course_subparsers.add_parser("modify")
    course_subparsers.add_parser("delete")

    # Lab commands
    lab_parser = subparsers.add_parser("lab")
    lab_subparsers = lab_parser.add_subparsers(
        dest="action",
        required=True
    )

    lab_subparsers.add_parser("add")
    lab_subparsers.add_parser("modify")
    lab_subparsers.add_parser("delete")

    # Room commands
    room_parser = subparsers.add_parser("room")
    room_subparsers = room_parser.add_subparsers(
        dest="action",
        required=True
    )
    
    room_subparsers.add_parser("add")
    room_subparsers.add_parser("modify")
    room_subparsers.add_parser("delete")

    # Timeslot commands
    timeslot_parser = subparsers.add_parser("timeslot")
    timeslot_subparsers = timeslot_parser.add_subparsers(
        dest="action",
        required=True
    )

    timeslot_subparsers.add_parser("add")
    timeslot_subparsers.add_parser("modify")
    timeslot_subparsers.add_parser("delete")

    # Pattern commands
    pattern_parser = subparsers.add_parser("pattern")
    pattern_subparsers = pattern_parser.add_subparsers(
        dest="action",
        required=True
    )

    pattern_subparsers.add_parser("add")
    pattern_subparsers.add_parser("modify")
    pattern_subparsers.add_parser("delete")

    # Meeting commands
    meeting_parser = subparsers.add_parser("meeting")
    meeting_subparsers = meeting_parser.add_subparsers(
        dest="action",
        required=True
    )

    meeting_subparsers.add_parser("add")
    meeting_subparsers.add_parser("modify")
    meeting_subparsers.add_parser("delete")

    # Config commands
    config_parser = subparsers.add_parser("config")
    config_subparsers = config_parser.add_subparsers(
        dest="action",
        required=True
    )

    config_subparsers.add_parser("print")
    config_subparsers.add_parser("save")
    config_subparsers.add_parser("load")

    # Schedule commands
    schedule_parser = subparsers.add_parser("schedule")
    schedule_subparsers = schedule_parser.add_subparsers(
        dest="action",
        required=True
    )

    schedule_subparsers.add_parser("summary")
    schedule_subparsers.add_parser("modify")
    schedule_subparsers.add_parser("replace")
    schedule_subparsers.add_parser("export")

    args = parser.parse_args()

    if args.command == "faculty":
        if args.action == "add":
            add_faculty()
        if args.action == "modify":
            modify_faculty()
        if args.action == "delete":
            delete_faculty()

    if args.command == "course":
        if args.action == "add":
            add_course()
        if args.action == "modify":
            modify_faculty()
        if args.action == "delete":
            delete_faculty()

    if args.command == "lab":
        if args.action == "add":
            add_lab()
        if args.action == "modify":
            modify_lab()
        if args.action == "delete":
            delete_lab()

    if args.command == "room":
        if args.action == "add":
            add_room()
        if args.action == "modify":
            modify_room()
        if args.action == "delete":
            delete_room()

    if args.command == "timeslot":
        if args.action == "add":
            add_timeslot()
        if args.action == "modify":
            modify_timeslot()
        if args.action == "delete":
            delete_timeslot()

    if args.command == "pattern":
        if args.action == "add":
            add_pattern()
        if args.action == "modify":
            modify_pattern()
        if args.action == "delete":
            delete_pattern()

    if args.command == "meeting":
        if args.action == "add":
            add_meeting()
        if args.action == "modify":
            modify_meeting()
        if args.action == "delete":
            delete_meeting()

    if args.command == "schedule":
        if args.action == "summary":
            schedule_summary()
        if args.action == "modify":
            modify_schedule()
        if args.action == "replace":
            replace_schedule()
        if args.action == "export":
            export_schedule()

    print(args)

if __name__ == "__main__":
    main()