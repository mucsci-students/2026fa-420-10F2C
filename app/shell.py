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


    def _confirm_discard_if_dirty(self, action_label):
        """Called before anything that would throw away unsaved changes
        (exiting, starting a new config, loading over the current one).
        Returns True if it's safe to proceed, False if the user backed
        out. Offers to save right here instead of making the user
        cancel, go save, then come back and retry."""
        if not self.session.dirty:
            return True

        print(f"You have unsaved changes. {action_label} will lose them.")
        choice = input("Save first? (y = save, n = discard and continue, c = cancel): ").strip().lower()

        if choice in ("c", "cancel"):
            return False
        if choice in ("y", "yes"):
            path = input("Path to save to (blank = reuse last path): ").strip()
            try:
                commands.save_config(self.session, path or None)
            except ConfigError as e:
                print(f"Error: {e}")
                print("Not proceeding, since the save failed -- your changes are still unsaved.")
                return False
            return True
        # "n"/anything else: proceed without saving
        return True

    # Guided entry point: welcome -> main menu -> submenus.
    def run(self):
        self._welcome()
        self._auto_load_example_config()
        while True:
            print("\nPlease select an option:\n")
            print("1. Configuration")
            print("2. Run Scheduler")
            print("3. View / Export Schedules")
            print("4. Config File (new / load / save / print / validate)")
            print("0. Exit\n")
            choice = input("Select: ").strip()

            if choice == "0":
                if not self._confirm_discard_if_dirty("Exiting"):
                    continue
                print("Goodbye!")
                break
            elif choice == "1":
                self._configuration_menu()
            elif choice == "2":
                self._run_scheduler_menu()
            elif choice == "3":
                self._schedules_menu()
            elif choice == "4":
                self._config_file_menu()
            elif choice == "help":
                self._help_main()
            else:
                print("Please enter a number from the menu.")

    def _welcome(self):
        print("=" * 60)
        print("   Welcome to the Scheduler Management Shell!")
        print("=" * 60)
        print("This tool manages a scheduler configuration, generates")
        print("schedules, and exports the results.")
        print("Type 'help' at any menu prompt to see what that screen's")
        print("options do.\n")

    # ---------------------------------------------------------------- #
    #  Contextual help -- one screen per menu, reached by typing        #
    #  'help' at that menu's "Select: " prompt. show_help() (bottom of  #
    #  this file) is the separate, older raw-command-syntax reference   #
    #  used by the argparse command-string path.                       #
    # ---------------------------------------------------------------- #
    def _print_help(self, title, body):
        bar = "=" * 60
        print(f"\n{bar}")
        print(f" Help: {title}")
        print(bar)
        print(body)

    def _help_main(self):
        self._print_help("Main Menu",
            "This tool builds a scheduler configuration (faculty,\n"
            "courses, rooms, labs, time slots, and class meeting\n"
            "patterns), generates conflict-free schedules from it, and\n"
            "lets you inspect or export the results.\n\n"
            "  1. Configuration              Add/modify/delete/view the\n"
            "                                pieces a schedule is built\n"
            "                                from.\n"
            "  2. Run Scheduler              Generate schedules from the\n"
            "                                current configuration.\n"
            "  3. View / Export Schedules    Inspect generated schedules,\n"
            "                                or export them to json/csv.\n"
            "  4. Config File                Start new / load / save /\n"
            "                                print / validate the\n"
            "                                configuration as a whole.\n"
            "  0. Exit                       Quit (you'll be warned first\n"
            "                                if you have unsaved changes).\n\n"
            "Type 'help' at any screen for details on that screen's own\n"
            "options.")

    def _auto_load_example_config(self):
        """Every session starts with the example dataset (17 courses, 9
        faculty, rooms/labs/time slots) already loaded, instead of
        empty, so CRUD has real data to work with immediately. Falls
        back to an empty session (still auto-provisioned on demand by
        _ensure_config()) if the file is missing or fails validation --
        never crashes the shell on startup."""
        example_path = "app/examples/config_example.json"
        try:
            self.session.load(example_path)
            print(f"Loaded example configuration from '{example_path}'.\n")
        except ConfigError as e:
            print(f"(Could not auto-load example config: {e})\n")

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
            print("8. Global Settings (generation limit / optimizer flags)")
            print("0. Back")
            choice = input("Select: ").strip()

            try:
                if choice == "0":
                    return
                elif choice == "1":
                    self._entity_menu("Faculty", commands.add_faculty, commands.modify_faculty,
                                       commands.delete_faculty, view=commands.view_faculty,
                                       help_text=self._ENTITY_HELP["Faculty"])
                elif choice == "2":
                    self._entity_menu("Course", commands.add_course, commands.modify_course,
                                       commands.delete_course, view=commands.view_course,
                                       help_text=self._ENTITY_HELP["Course"])
                elif choice == "3":
                    self._entity_menu("Room", commands.add_room, commands.modify_room,
                                       commands.delete_room, view=commands.view_room,
                                       help_text=self._ENTITY_HELP["Room"])
                elif choice == "4":
                    self._entity_menu("Lab", commands.add_lab, commands.modify_lab,
                                       commands.delete_lab, view=commands.view_lab,
                                       help_text=self._ENTITY_HELP["Lab"])
                elif choice == "5":
                    self._entity_menu("Time Slot", commands.add_timeslot, commands.modify_timeslot,
                                       commands.delete_timeslot,
                                       extra_actions={"Modify global timing options (gap/overlap)":
                                                       commands.modify_timing_options},
                                       help_text=self._ENTITY_HELP["Time Slot"])
                elif choice == "6":
                    self._entity_menu("Class Pattern", commands.add_pattern, commands.modify_pattern,
                                       commands.delete_pattern,
                                       help_text=self._ENTITY_HELP["Class Pattern"])
                elif choice == "7":
                    self._entity_menu("Meeting", commands.add_meeting, commands.modify_meeting,
                                       commands.delete_meeting,
                                       help_text=self._ENTITY_HELP["Meeting"])
                elif choice == "8":
                    self._settings_menu()
                elif choice == "help":
                    self._help_configuration()
                else:
                    print("Please enter a number from the menu.")
            except ConfigError as e:
                print(f"Error: {e}")

    def _help_configuration(self):
        self._print_help("Configuration",
            "These are the pieces a schedule is generated from. They\n"
            "reference each other, so it's easiest to set them up in\n"
            "roughly this order:\n\n"
            "  5. Time Slots        The weekday time blocks meetings can\n"
            "                       be scheduled into, plus the global\n"
            "                       gap/overlap rules.\n"
            "  6. Class Meeting Patterns\n"
            "                       Templates (e.g. \"MWF, 50 min\") for\n"
            "                       how a course's credits break into\n"
            "                       meetings. A course needs a matching\n"
            "                       pattern to exist before it can be\n"
            "                       added.\n"
            "  1. Faculty           Instructors: credit load, teaching\n"
            "                       days/availability, and course/room/\n"
            "                       lab preferences.\n"
            "  3. Rooms             Physical classrooms: capacity,\n"
            "                       features, availability.\n"
            "  4. Labs              Same idea as Rooms, for lab sessions.\n"
            "  2. Courses           One section per entry; ties together\n"
            "                       credits/patterns, rooms/labs, faculty,\n"
            "                       and conflicts with other courses.\n"
            "  7. Meetings          Edit a single meeting inside a Class\n"
            "                       Meeting Pattern without re-entering\n"
            "                       the whole pattern.\n"
            "  8. Global Settings   Generation limit and optimizer flags\n"
            "                       (soft scheduling preferences).\n\n"
            "Rooms, Labs, and Faculty can't be deleted while a course\n"
            "still references them -- remove the reference from the\n"
            "course first.\n\n"
            "Type 'help' inside any of these screens for details specific\n"
            "to that entity.")

    def _ensure_config(self):
        """Entity/settings menus no longer require an explicit 'start a
        new configuration' step first -- the first time one is opened
        with nothing loaded yet, silently provision a blank config so
        the user can go straight to add/modify/delete. Explicit
        new/load/save/print/validate still live in the top-level Config
        File menu for resetting or working with a real file."""
        if self.session.config is None:
            commands.new_config(self.session)

    # Add/modify/delete/view for one entity; reused for every entity type.
    # extra_actions is an optional {label: fn} dict for entity-specific
    # actions beyond plain CRUD (e.g. time slots' global timing options).
    # help_text is that entity's fully-written help body (see
    # _ENTITY_HELP below) -- entities differ enough (name- vs index-
    # vs day-based lookup, different delete-time reference checks) that
    # a single generated template would either be vague or wrong for
    # some of them, so each one is written out in full instead.
    def _entity_menu(self, label, add_fn, modify_fn, delete_fn, view=None, extra_actions=None,
                      help_text=None):
        self._ensure_config()
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
                elif choice == "help":
                    self._print_help(label, help_text or f"No detailed help is written for {label} yet.")
                else:
                    print("Please enter a number from the menu.")
            except ConfigError as e:
                print(f"Error: {e}")

    # Per-entity help bodies for _entity_menu, keyed by the same label
    # passed to _entity_menu(). Written out individually rather than
    # generated because lookup keys (name vs. index vs. day+index),
    # what "modify" re-prompts for, and delete-time reference checks
    # all differ per entity -- see commands.py for each one's real
    # behavior.
    _ENTITY_HELP = {
        "Faculty":
            "An instructor available to teach course sections.\n\n"
            "Records: credit load range (min/max), unique-course limit\n"
            "(a value of 1 or less shows as \"Adjunct\", otherwise\n"
            "\"Full-Time\"), mandatory teaching days, weekly availability\n"
            "windows, and weighted preferences for which courses/rooms/\n"
            "labs they'd like to be assigned.\n\n"
            "  1. Add Faculty      Prompts for all fields above.\n"
            "  2. Modify Faculty   Looked up by name. Every field is\n"
            "                      shown with its current value --\n"
            "                      blank keeps it, so you only need to\n"
            "                      type the ones you're changing.\n"
            "  3. Delete Faculty    Looked up by name. Blocked if any\n"
            "                      course still lists this person as a\n"
            "                      candidate faculty member -- remove\n"
            "                      them from those courses first.\n"
            "  4. View all Faculty records   Prints every record with\n"
            "                      full availability and preference\n"
            "                      detail.\n"
            "  0. Back",

        "Course":
            "One section of a course to be scheduled (e.g. \"CS 101\").\n\n"
            "A course's credit count must match an existing, enabled\n"
            "Class Meeting Pattern (Configuration -> Class Meeting\n"
            "Patterns) or it will be rejected -- set patterns up first\n"
            "if you haven't.\n\n"
            "Records: course ID, section ID (blank = auto-numbered),\n"
            "credits, expected enrollment, modality (in_person/online/\n"
            "hybrid -- online courses skip rooms/labs entirely),\n"
            "candidate rooms/labs with required features, other courses\n"
            "this one conflicts with (can never overlap), and candidate\n"
            "faculty (blank = derive from faculty course preferences).\n\n"
            "  1. Add Course        Prompts for all fields above.\n"
            "  2. Modify Course     Shows a numbered list of existing\n"
            "                       sections; pick an index, then edit\n"
            "                       any field -- each is shown with its\n"
            "                       current value and blank keeps it.\n"
            "  3. Delete Course     Pick an index. If it's the last\n"
            "                       section of that course ID, blocked\n"
            "                       while another course's conflict list\n"
            "                       or a faculty member's course\n"
            "                       preferences still name it.\n"
            "  4. View all Course records   Prints every section.\n"
            "  0. Back",

        "Room":
            "A physical classroom courses can meet in.\n\n"
            "Records: capacity, features this room supplies (comma-\n"
            "separated tags, e.g. \"projector\", matched against a\n"
            "course's required room features), and an optional\n"
            "restricted weekday availability (default: available any\n"
            "time).\n\n"
            "  1. Add Room          Prompts for all fields above.\n"
            "  2. Modify Room       Looked up by name. Each field is\n"
            "                       shown with its current value --\n"
            "                       blank keeps it.\n"
            "  3. Delete Room       Looked up by name. Blocked if any\n"
            "                       course's candidate room list still\n"
            "                       names it.\n"
            "  4. View all Room records   Prints every room with its\n"
            "                       features and availability.\n"
            "  0. Back",

        "Lab":
            "A lab space, used the same way as a Room but for a course's\n"
            "lab meetings.\n\n"
            "Records: capacity, supplied features, and optional\n"
            "restricted weekday availability.\n\n"
            "  1. Add Lab           Prompts for all fields above.\n"
            "  2. Modify Lab        Looked up by name. Each field is\n"
            "                       shown with its current value --\n"
            "                       blank keeps it.\n"
            "  3. Delete Lab        Looked up by name. Blocked if any\n"
            "                       course's candidate lab list still\n"
            "                       names it.\n"
            "  4. View all Lab records   Prints every lab with its\n"
            "                       features and availability.\n"
            "  0. Back",

        "Time Slot":
            "The Monday-Friday time blocks (start-end + spacing) that\n"
            "class meetings can be scheduled into -- separate from Class\n"
            "Meeting Patterns, which decide how many meetings a course\n"
            "needs and how long each one runs.\n\n"
            "  1. Add Time Slot      Pick a day, then enter a start/end/\n"
            "                        spacing. Rejected if it overlaps a\n"
            "                        block already on that day.\n"
            "  2. Modify Time Slot   Pick a day, see its blocks listed by\n"
            "                        index, pick one -- start/end/\n"
            "                        spacing are shown with their\n"
            "                        current values, blank keeps them.\n"
            "  3. Delete Time Slot   Pick a day and index. Blocked if\n"
            "                        it's the only block on that day --\n"
            "                        every weekday needs at least one.\n"
            "  4. Modify global timing options (gap/overlap)\n"
            "                        Sets the max gap and min overlap (in\n"
            "                        minutes) allowed between two\n"
            "                        meetings placed back-to-back --\n"
            "                        applies across every day.\n"
            "  0. Back",

        "Class Pattern":
            "A weekly meeting template -- e.g. \"3 credits: MWF, 50 min\"\n"
            "-- that says how a course's credit hours break into\n"
            "meetings across the week. A course can only be added, or\n"
            "kept, if a pattern exists matching its credit count.\n\n"
            "There's no name/ID here: patterns are listed and picked by\n"
            "position (index), shown automatically before you modify or\n"
            "delete one.\n\n"
            "Records: credits, one or more meetings (each with a day,\n"
            "duration, lab flag, delivery mode, and optional fixed start\n"
            "time), an optional pattern-level fixed start time, and\n"
            "whether the pattern starts disabled.\n\n"
            "  1. Add Class Pattern     Prompts for credits, then one or\n"
            "                          more meetings.\n"
            "  2. Modify Class Pattern  Pick an index. Credits/start\n"
            "                          time/disabled are shown with\n"
            "                          their current values (blank\n"
            "                          keeps them) -- meetings are left\n"
            "                          untouched here; edit those via\n"
            "                          the Meeting menu instead.\n"
            "  3. Delete Class Pattern  Pick an index. Not reference-\n"
            "                          checked -- if a course still\n"
            "                          needs this credit count, it will\n"
            "                          simply start failing validation\n"
            "                          next time it's added or modified.\n"
            "  0. Back",

        "Meeting":
            "One meeting slot -- day, duration, lab flag, delivery mode,\n"
            "and an optional fixed start time -- that lives inside a\n"
            "Class Meeting Pattern. Use this to tweak a single meeting\n"
            "without re-entering the whole pattern.\n\n"
            "There's no standalone list here either: Add/Modify/Delete\n"
            "all start by showing you the patterns, then that pattern's\n"
            "meetings, both by index.\n\n"
            "  1. Add Meeting        Pick a pattern, then enter one new\n"
            "                        meeting for it.\n"
            "  2. Modify Meeting     Pick a pattern, then a meeting on\n"
            "                        it. Each field (day/duration/lab/\n"
            "                        delivery/start time) is shown with\n"
            "                        its current value; blank keeps it.\n"
            "  3. Delete Meeting     Pick a pattern, then a meeting on\n"
            "                        it. Blocked if it's the pattern's\n"
            "                        only meeting -- delete the whole\n"
            "                        pattern instead if you don't need\n"
            "                        it.\n"
            "  0. Back",
    }

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
                    if not self._confirm_discard_if_dirty("Starting a new configuration"):
                        continue
                    commands.new_config(self.session)
                    return
                elif choice == "2":
                    if not self._confirm_discard_if_dirty("Loading a different configuration"):
                        continue
                    path = input("Path to load (blank = example config): ").strip()
                    path = path or "app/examples/config_example.json"
                    commands.load_config(self.session, path)
                elif choice == "3":
                    path = input("Path to save to (blank = reuse last path): ").strip()
                    commands.save_config(self.session, path or None)
                elif choice == "4":
                    commands.print_config(self.session)
                elif choice == "5":
                    commands.validate_config(self.session)
                elif choice == "help":
                    self._help_config_file()
                else:
                    print("Please enter a number from the menu.")
            except ConfigError as e:
                print(f"Error: {e}")

    def _help_config_file(self):
        self._print_help("Config File",
            "Operations on the configuration as a whole, as opposed to\n"
            "editing one entity inside it (that's the Configuration\n"
            "menu).\n\n"
            "  1. Start a new configuration    Discards the current one\n"
            "                                  (with an unsaved-changes\n"
            "                                  prompt first) and starts\n"
            "                                  empty.\n"
            "  2. Load a configuration from a file\n"
            "                                  Blank path loads the\n"
            "                                  built-in example config.\n"
            "  3. Save the current configuration\n"
            "                                  Blank path reuses the\n"
            "                                  last path you saved to or\n"
            "                                  loaded from.\n"
            "  4. Print the current configuration\n"
            "                                  Dumps it to the screen.\n"
            "  5. Validate the current configuration\n"
            "                                  Runs the scheduler\n"
            "                                  library's validation\n"
            "                                  without saving or\n"
            "                                  changing anything.\n"
            "  0. Back")

    def _settings_menu(self):
        self._ensure_config()
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
                elif choice == "help":
                    self._help_settings()
                else:
                    print("Please enter a number from the menu.")
            except ConfigError as e:
                print(f"Error: {e}")

    def _help_settings(self):
        self._print_help("Global Settings",
            "Settings that apply to the whole configuration rather than\n"
            "one entity.\n\n"
            "  1. Set generation limit        The max number of\n"
            "                                 candidate schedules the\n"
            "                                 scheduler will produce\n"
            "                                 when you run it.\n"
            "  2. Reset generation limit      Restores the library's\n"
            "     to default                  default limit.\n"
            "  3. Enable an optimizer flag    Turns on a soft scheduling\n"
            "                                 preference. Valid flags:\n"
            "                                 faculty_course,\n"
            "                                 faculty_room, faculty_lab,\n"
            "                                 same_room, same_lab,\n"
            "                                 pack_rooms, pack_labs.\n"
            "  4. Disable an optimizer flag   Turns one back off.\n"
            "  0. Back")

    # Main menu option 2.
    def _run_scheduler_menu(self):
        self._ensure_config()
        print("\n--- Run Scheduler ---")
        while True:
            limit_input = input(
                "Schedule generation limit (blank = use config's limit, "
                "'help' for info): "
            ).strip()
            if limit_input.lower() == "help":
                self._help_run_scheduler()
                continue
            break
        limit_override = int(limit_input) if limit_input.isdigit() else None
        try:
            commands.generate_schedule(self.session, limit_override=limit_override)
        except ConfigError as e:
            print(f"Error: {e}")

    def _help_run_scheduler(self):
        self._print_help("Run Scheduler",
            "Generates schedules from the current configuration.\n\n"
            "You'll be asked for a generation limit -- the max number of\n"
            "candidate schedules to produce. Leave it blank to use the\n"
            "limit from Global Settings (Configuration -> Global\n"
            "Settings), or enter a number to override it just for this\n"
            "run.")

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
                elif choice == "help":
                    self._help_schedules()
                else:
                    print("Please enter a number from the menu.")
            except ConfigError as e:
                print(f"Error: {e}")

    def _help_schedules(self):
        self._print_help("Schedules",
            "Inspect or export schedules already generated by Run\n"
            "Scheduler -- this screen doesn't generate anything itself.\n\n"
            "  1. Summary of generated schedules   A quick overview of\n"
            "                                      each generated\n"
            "                                      schedule.\n"
            "  2. View one schedule by index       Full detail for a\n"
            "                                      single schedule.\n"
            "  3. Export schedules                 To json or csv,\n"
            "                                      either one schedule\n"
            "                                      by index or all of\n"
            "                                      them.\n"
            "  4. Clear generated schedules        Drops every schedule\n"
            "                                      generated so far.\n"
            "  0. Back")

    def show_help(self):
        """Raw command-string syntax reference for handle_command()/
        _dispatch() (the argparse path). Not shown by the guided menus
        any more -- those each have their own contextual help above,
        reached by typing 'help' at that menu's prompt."""
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