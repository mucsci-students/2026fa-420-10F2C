import argparse
from app.commands import *
from app.Cli.facultyComm import add_faculty, modify_faculty, delete_faculty
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

        course_subparsers.add_parser("modify")
        course_subparsers.add_parser("add")
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

            # Help command
        help_parser = subparsers.add_parser(
              "help",
              help = "Display available commands"
        )

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
                    modify_course()
            if args.action == "delete":
                    delete_course()

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
                    
        if args.command == "config": 
            if args.action == "print":
                  print_config() # these still need to be written
            if args.action == "save":
                  save_config() #these still need to be written
            if args.action == "load": 
                  load_config() #these still need to be written
        if args.command == "help": 
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
        print("\n" \
        "Available commands:" \
        "\n\nfaculty     <add,modify,delete> \n" \
        "course      <add,modify,delete> \n" \
        "lab         <add,modify,delete\n" \
        "room        <add,modify,delete>\n" \
        "timeslot    <add,modify,delete> \n" \
        "pattern     <add,modify,delete>\n" \
        "meeting     <add,modify,delete> \n" \
        "config      <print,load,save \n" \
        "schedule    <summary,modify,replace,export>\n" \
        "help        Display available commands\n" \
        "exit        Exit the scheduler shell")


