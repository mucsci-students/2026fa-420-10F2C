import argparse
from app.session import Session, ConfigError
from app import commands
# Handles the interactive shell. Owns one Session for the whole run and
# passes it into every command function.
# run() is a guided numbered-menu flow (welcome -> pick area -> pick
# action) that just calls the same commands.py functions handle_command()
# used before -- no CRUD logic is duplicated here. The old argparse
# command-string path (handle_command/_dispatch) is left in below too.
class SchedulerShell:

    def __init__(self):
        self.parser = self.create_parser()
        self.session = Session()

# Builds the argparse parser for raw command-string input (unchanged).
    def create_parser(self):
        parser = argparse.ArgumentParser(
                description="Course scheduling configuration tool"
            )

        subparsers = parser.add_subparsers(
                dest="command",
                required=True
            )

        faculty_parser = subparsers.add_parser("faculty")
        faculty_subparsers = faculty_parser.add_subparsers(dest="action", required=True)
        faculty_subparsers.add_parser("add")
        faculty_subparsers.add_parser("modify")
        faculty_subparsers.add_parser("delete")
        faculty_subparsers.add_parser("view")

        course_parser = subparsers.add_parser("course")
        course_subparsers = course_parser.add_subparsers(dest="action", required=True)
        course_subparsers.add_parser("modify")
        course_subparsers.add_parser("add")
        course_subparsers.add_parser("delete")

        lab_parser = subparsers.add_parser("lab")
        lab_subparsers = lab_parser.add_subparsers(dest="action", required=True)
        lab_subparsers.add_parser("add")
        lab_subparsers.add_parser("modify")
        lab_subparsers.add_parser("delete")

        room_parser = subparsers.add_parser("room")
        room_subparsers = room_parser.add_subparsers(dest="action", required=True)
        room_subparsers.add_parser("add")
        room_subparsers.add_parser("modify")
        room_subparsers.add_parser("delete")

        timeslot_parser = subparsers.add_parser("timeslot")
        timeslot_subparsers = timeslot_parser.add_subparsers(dest="action", required=True)
        timeslot_subparsers.add_parser("add")
        timeslot_subparsers.add_parser("modify")
        timeslot_subparsers.add_parser("delete")
        timeslot_subparsers.add_parser("timing")

        pattern_parser = subparsers.add_parser("pattern")
        pattern_subparsers = pattern_parser.add_subparsers(dest="action", required=True)
        pattern_subparsers.add_parser("add")
        pattern_subparsers.add_parser("modify")
        pattern_subparsers.add_parser("delete")

        meeting_parser = subparsers.add_parser("meeting")
        meeting_subparsers = meeting_parser.add_subparsers(dest="action", required=True)
        meeting_subparsers.add_parser("add")
        meeting_subparsers.add_parser("modify")
        meeting_subparsers.add_parser("delete")

        config_parser = subparsers.add_parser("config")
        config_subparsers = config_parser.add_subparsers(dest="action", required=True)
        config_subparsers.add_parser("new")
        config_subparsers.add_parser("print")
        p_save = config_subparsers.add_parser("save")
        p_save.add_argument("path", nargs="?", default=None)
        p_load = config_subparsers.add_parser("load")
        p_load.add_argument("path")
        config_subparsers.add_parser("validate")

        settings_parser = subparsers.add_parser("settings")
        settings_subparsers = settings_parser.add_subparsers(dest="action", required=True)
        p_limit = settings_subparsers.add_parser("limit")
        p_limit.add_argument("value", nargs="?", type=int, default=None)
        p_limit.add_argument("--reset", action="store_true")
        p_flag_on = settings_subparsers.add_parser("enable-flag")
        p_flag_on.add_argument("flag")
        p_flag_off = settings_subparsers.add_parser("disable-flag")
        p_flag_off.add_argument("flag")

        help_parser = subparsers.add_parser("help", help="Display available commands")

        schedule_parser = subparsers.add_parser("schedule")
        schedule_subparsers = schedule_parser.add_subparsers(dest="action", required=True)
        p_gen = schedule_subparsers.add_parser("generate")
        p_gen.add_argument("--limit", type=int, default=None)
        schedule_subparsers.add_parser("summary")
        p_view = schedule_subparsers.add_parser("view")
        p_view.add_argument("index", type=int)
        schedule_subparsers.add_parser("clear")
        p_export = schedule_subparsers.add_parser("export")
        p_export.add_argument("format", choices=["json", "csv"])
        p_export.add_argument("path")
        p_export.add_argument("--index", type=int, default=None,
                               help="Export one schedule by index instead of the whole set")
        p_export.add_argument("--overwrite", action="store_true")

        return parser


# Parses a raw command string and dispatches it (unchanged).
    def handle_command(self, command):
        try:
            args = self.parser.parse_args(command.split())
        except SystemExit:
            print("Type 'help' to see available commands")
            return

        try:
            self._dispatch(args)
        except ConfigError as e:
            # Every backbone command raises ConfigError for user-facing
            # problems (no config loaded, bad file, failed validation).
            # Catching it here means one bad command never kills the
            # session (Req #3: 'recover from invalid input without
            # terminating the session').
            print(f"Error: {e}")

    def _dispatch(self, args):
        session = self.session

        if args.command == "faculty":
            {
                "add": commands.add_faculty,
                "modify": commands.modify_faculty,
                "delete": commands.delete_faculty,
                "view": commands.view_faculty,
            }[args.action](session)

        elif args.command == "course":
            {
                "add": commands.add_course,
                "modify": commands.modify_course,
                "delete": commands.delete_course,
            }[args.action](session)

        elif args.command == "lab":
            {
                "add": commands.add_lab,
                "modify": commands.modify_lab,
                "delete": commands.delete_lab,
            }[args.action](session)

        elif args.command == "room":
            {
                "add": commands.add_room,
                "modify": commands.modify_room,
                "delete": commands.delete_room,
            }[args.action](session)

        elif args.command == "timeslot":
            {
                "add": commands.add_timeslot,
                "modify": commands.modify_timeslot,
                "delete": commands.delete_timeslot,
                "timing": commands.modify_timing_options,
            }[args.action](session)

        elif args.command == "pattern":
            {
                "add": commands.add_pattern,
                "modify": commands.modify_pattern,
                "delete": commands.delete_pattern,
            }[args.action](session)

        elif args.command == "meeting":
            {
                "add": commands.add_meeting,
                "modify": commands.modify_meeting,
                "delete": commands.delete_meeting,
            }[args.action](session)

        elif args.command == "schedule":
            if args.action == "generate":
                commands.generate_schedule(session, limit_override=args.limit)
            elif args.action == "summary":
                commands.schedule_summary(session)
            elif args.action == "view":
                commands.view_schedule(session, args.index)
            elif args.action == "clear":
                commands.clear_schedules(session)
            elif args.action == "export":
                commands.export_schedule(session, args.format, args.path,
                                          index=args.index, overwrite=args.overwrite)

        elif args.command == "config":
            if args.action == "new":
                commands.new_config(session)
            elif args.action == "print":
                commands.print_config(session)
            elif args.action == "save":
                commands.save_config(session, args.path)
            elif args.action == "load":
                commands.load_config(session, args.path)
            elif args.action == "validate":
                commands.validate_config(session)

        elif args.command == "settings":
            if args.action == "limit":
                if args.reset:
                    commands.reset_generation_limit(session)
                elif args.value is not None:
                    commands.set_generation_limit(session, args.value)
                else:
                    print("Usage: settings limit <value> | settings limit --reset")
            elif args.action == "enable-flag":
                commands.enable_optimizer_flag(session, args.flag)
            elif args.action == "disable-flag":
                commands.disable_optimizer_flag(session, args.flag)

        elif args.command == "help":
            self.show_help()


# Guided entry point: welcome -> main menu -> submenus.
    def run(self):
        self._welcome()
        while True:
            print("\nPlease select an option:\n")
            print("1. Configuration")
            print("2. Run Scheduler")
            print("3. View / Export Schedules")
            print("0. Exit\n")
            choice = input("Select: ").strip()

            if choice == "0":
                print("Goodbye!")
                break
            elif choice == "1":
                self._configuration_menu()
            elif choice == "2":
                self._run_scheduler_menu()
            elif choice == "3":
                self._schedules_menu()
            else:
                print("Please enter 0, 1, 2, or 3.")

    def _welcome(self):
        print("=" * 60)
        print("   Welcome to the Scheduler Management Shell!")
        print("=" * 60)
        print("This tool manages a scheduler configuration, generates")
        print("schedules, and exports the results.")
        print("Type 'help' any time you see a prompt for the raw command")
        print("syntax instead, if you'd rather type commands directly.\n")

    # Pick a configuration area.
    def _configuration_menu(self):
        while True:
            print("\n--- Configuration ---")
            print("1. Faculty")
            print("2. Courses")
            print("3. Rooms")
            print("4. Labs")
            print("5. Time Slots")
            print("6. Class Meeting Patterns")
            print("7. Meetings")
            print("8. Config file (new / load / save / print / validate)")
            print("9. Global Settings (generation limit / optimizer flags)")
            print("0. Back")
            choice = input("Select: ").strip()

            try:
                if choice == "0":
                    return
                elif choice == "1":
                    self._entity_menu("Faculty", commands.add_faculty, commands.modify_faculty,
                                       commands.delete_faculty, view=commands.view_faculty)
                elif choice == "2":
                    self._entity_menu("Course", commands.add_course, commands.modify_course,
                                       commands.delete_course)
                elif choice == "3":
                    self._entity_menu("Room", commands.add_room, commands.modify_room,
                                       commands.delete_room)
                elif choice == "4":
                    self._entity_menu("Lab", commands.add_lab, commands.modify_lab,
                                       commands.delete_lab)
                elif choice == "5":
                    self._entity_menu("Time Slot", commands.add_timeslot, commands.modify_timeslot,
                                       commands.delete_timeslot,
                                       extra_actions={"Modify global timing options (gap/overlap)":
                                                       commands.modify_timing_options})
                elif choice == "6":
                    self._entity_menu("Class Pattern", commands.add_pattern, commands.modify_pattern,
                                       commands.delete_pattern)
                elif choice == "7":
                    self._entity_menu("Meeting", commands.add_meeting, commands.modify_meeting,
                                       commands.delete_meeting)
                elif choice == "8":
                    self._config_file_menu()
                elif choice == "9":
                    self._settings_menu()
                else:
                    print("Please enter a number from the menu.")
            except ConfigError as e:
                print(f"Error: {e}")

    # Add/modify/delete/view for one entity; reused for every entity type.
    # extra_actions is an optional {label: fn} dict for entity-specific
    # actions beyond plain CRUD (e.g. time slots' global timing options).
    def _entity_menu(self, label, add_fn, modify_fn, delete_fn, view=None, extra_actions=None):
        extra_actions = extra_actions or {}
        while True:
            print(f"\n--- {label} ---")
            print(f"1. Add {label}")
            print(f"2. Modify {label}")
            print(f"3. Delete {label}")
            next_num = 4
            view_num = None
            if view is not None:
                print(f"{next_num}. View all {label} records")
                view_num = next_num
                next_num += 1
            extra_nums = {}
            for extra_label, fn in extra_actions.items():
                print(f"{next_num}. {extra_label}")
                extra_nums[str(next_num)] = fn
                next_num += 1
            print("0. Back")
            choice = input("Select: ").strip()

            try:
                if choice == "0":
                    return
                elif choice == "1":
                    add_fn(self.session)
                elif choice == "2":
                    modify_fn(self.session)
                elif choice == "3":
                    delete_fn(self.session)
                elif view_num is not None and choice == str(view_num):
                    view(self.session)
                elif choice in extra_nums:
                    extra_nums[choice](self.session)
                else:
                    print("Please enter a number from the menu.")
            except ConfigError as e:
                print(f"Error: {e}")

    def _config_file_menu(self):
        while True:
            print("\n--- Config File ---")
            print("1. Start a new configuration")
            print("2. Load a configuration from a file")
            print("3. Save the current configuration")
            print("4. Print the current configuration")
            print("5. Validate the current configuration")
            print("0. Back")
            choice = input("Select: ").strip()

            try:
                if choice == "0":
                    return
                elif choice == "1":
                    commands.new_config(self.session)
                elif choice == "2":
                    path = input("Path to load: ").strip()
                    commands.load_config(self.session, path)
                elif choice == "3":
                    path = input("Path to save to (blank = reuse last path): ").strip()
                    commands.save_config(self.session, path or None)
                elif choice == "4":
                    commands.print_config(self.session)
                elif choice == "5":
                    commands.validate_config(self.session)
                else:
                    print("Please enter a number from the menu.")
            except ConfigError as e:
                print(f"Error: {e}")

    def _settings_menu(self):
        while True:
            print("\n--- Global Settings ---")
            print("1. Set generation limit")
            print("2. Reset generation limit to default")
            print("3. Enable an optimizer flag")
            print("4. Disable an optimizer flag")
            print("0. Back")
            choice = input("Select: ").strip()

            try:
                if choice == "0":
                    return
                elif choice == "1":
                    value_input = input("New generation limit: ").strip()
                    if not value_input.lstrip("-").isdigit():
                        print("Please enter a whole number.")
                        continue
                    commands.set_generation_limit(self.session, int(value_input))
                elif choice == "2":
                    commands.reset_generation_limit(self.session)
                elif choice == "3":
                    flag = input("Flag to enable (e.g. faculty_course, same_room, pack_labs): ").strip()
                    commands.enable_optimizer_flag(self.session, flag)
                elif choice == "4":
                    flag = input("Flag to disable: ").strip()
                    commands.disable_optimizer_flag(self.session, flag)
                else:
                    print("Please enter a number from the menu.")
            except ConfigError as e:
                print(f"Error: {e}")

    # Main menu option 2.
    def _run_scheduler_menu(self):
        print("\n--- Run Scheduler ---")
        limit_input = input("Schedule generation limit (blank = use config's limit): ").strip()
        limit_override = int(limit_input) if limit_input.isdigit() else None
        try:
            commands.generate_schedule(self.session, limit_override=limit_override)
        except ConfigError as e:
            print(f"Error: {e}")

    # Main menu option 3.
    def _schedules_menu(self):
        while True:
            print("\n--- Schedules ---")
            print("1. Summary of generated schedules")
            print("2. View one schedule by index")
            print("3. Export schedules")
            print("4. Clear generated schedules")
            print("0. Back")
            choice = input("Select: ").strip()

            try:
                if choice == "0":
                    return
                elif choice == "1":
                    commands.schedule_summary(self.session)
                elif choice == "2":
                    idx = input("Schedule index: ").strip()
                    if idx.isdigit():
                        commands.view_schedule(self.session, int(idx))
                    else:
                        print("Please enter a valid integer index.")
                elif choice == "3":
                    fmt = input("Format (json/csv): ").strip().lower()
                    if fmt not in ("json", "csv"):
                        print("Please enter 'json' or 'csv'.")
                        continue
                    path = input("Output file path: ").strip()
                    idx_input = input("Export a single index, or blank for all: ").strip()
                    index = int(idx_input) if idx_input.isdigit() else None
                    overwrite_input = input("Overwrite if it exists? (y/n): ").strip().lower()
                    commands.export_schedule(self.session, fmt, path, index=index,
                                              overwrite=overwrite_input in ("y", "yes"))
                elif choice == "4":
                    commands.clear_schedules(self.session)
                else:
                    print("Please enter a number from the menu.")
            except ConfigError as e:
                print(f"Error: {e}")

    def show_help(self):
        print("\n"
              "Available commands:\n\n"
              "faculty     <add,modify,delete,view>\n"
              "course      <add,modify,delete>\n"
              "lab         <add,modify,delete>\n"
              "room        <add,modify,delete>\n"
              "timeslot    <add,modify,delete,timing>\n"
              "settings    <limit N,limit --reset,enable-flag F,disable-flag F>\n"
              "pattern     <add,modify,delete>\n"
              "meeting     <add,modify,delete>\n"
              "config      <new,print,load <path>,save [path],validate>\n"
              "schedule    <generate [--limit N],summary,view <index>,clear,export <json|csv> <path>>\n"
              "help        Display available commands\n"
              "exit        Exit the scheduler shell")