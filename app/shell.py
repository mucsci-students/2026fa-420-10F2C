import argparse
from app.commands import *
from app import add_faculty, modify_faculty, delete_faculty
# ----------------------------------------------------------------------------------------------------------------------- #
#                       Handles the interactive shell and user commands for the scheduler                                 #   
# ----------------------------------------------------------------------------------------------------------------------- #
class SchedulerShell: 

    def __init__(self):
        self.parser = self.create_parser()
        
# ----------------------------------------------------------------------------------------------------------------------- #
#            Creates the argparse parser used by the shell to recognize and validate user commands.                       #  
#            Each main command (faculty, course, lab, etc.) has its own set of actions that the user  can choose from.    #  
#            The parser is returned and stored by the shell so it can be reused whenever the user enters a command.       #  
# ----------------------------------------------------------------------------------------------------------------------- #
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


# ----------------------------------------------------------------------------------------------------------------------- #
#                   parses a command entered by the user and validates it against the shells argparse configuration       #  
#                   that corresponds to the appropriate command function.                                                 #   
#                   Invalid commands are caught so that argparse does not terminate the shell,                            #  
#                   allowing for multiple commands to be entered                                                          #
# ----------------------------------------------------------------------------------------------------------------------- #
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

        elif args.command == "help":
            self.show_help()



        #print(args)






# ----------------------------------------------------------------------------------------------------------------------- #
#           This is what starts our shell, a simple while True loops that persists unless an exit command is issued.      #
#                           Allows us to enter multiple commands without invoking main everytime                          #
# ----------------------------------------------------------------------------------------------------------------------- #
    def run(self):
        print("*********************************************************************************")
        print("Running Shell....\n\n\n\n\n\n")
        print("\n\n\n\n\nWelcome to the Scheduler Management Shell!\nUse this shell to manage scheduler configuration, generate schedules,and export scheduling results.\n\n\nType 'help' to see available commands.\n\nType 'exit' to leave the shell.\n")
        while True: 
            command = input("Scheduler> ")

            if command == 'exit' or command == 'quit': 
                break

            self.handle_command(command)





# --------------------------------------------------------------------------------------------------------------------------- #
#                           Help function here, so that help is handled by the shell and not commands                         #
# --------------------------------------------------------------------------------------------------------------------------- #

    def show_help(self):
        print("\n"
              "Available commands:\n\n"
              "faculty     <add,modify,delete,view>\n"
              "course      <add,modify,delete>\n"
              "lab         <add,modify,delete>\n"
              "room        <add,modify,delete>\n"
              "timeslot    <add,modify,delete>\n"
              "pattern     <add,modify,delete>\n"
              "meeting     <add,modify,delete>\n"
              "config      <new,print,load <path>,save [path],validate>\n"
              "schedule    <generate [--limit N],summary,view <index>,clear,export <json|csv> <path>>\n"
              "help        Display available commands\n"
              "exit        Exit the scheduler shell")