# ----------------------------------------------------------------------------------------------------------------------- #
#                                                                                                                         #
#                                      Main.py's only purpose is to start shell.                                          #   
#                                      we simply import the shell and run it                                              #   
#                                                                                                                         #
# ----------------------------------------------------------------------------------------------------------------------- #
from app.shell import SchedulerShell 


shell = SchedulerShell()
shell.run()