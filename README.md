# 2026fa-420-10F2C

## Contributors
Calvin Becker,
Alan Reider, 
Henry Malesker, 
Joseph Lucks, 
Samsong Tamang, 
James Liranzo, 

# Course Scheduler

An interactive command-line tool for building, validating, and solving university course scheduling configurations. It wraps the [`course-constraint-scheduler`](https://pypi.org/project/course-constraint-scheduler/) library, which uses the Z3 solver to find schedules that satisfy every hard constraint (faculty availability, room and lab capacity, course conflicts, meeting patterns).

## Install and Start

**Prerequisites:** Python 3.14+, [uv](https://docs.astral.sh/uv/), and Git.

```bash
git clone git@github.com:mucsci-students/2026fa-420-10F2C.git
cd 2026fa-420-10F2C
uv sync                      # creates a venv and installs pinned dependencies
uv run python main.py        # starts the shell (run from the repo root)
uv run pytest                # optional: run the test suite
```

On startup the shell auto-loads the example dataset (`app/examples/config_example.json`), so you can explore immediately.

## Getting Help

At the main menu, type `help` to list every available command. Every menu also has a `0. Back` option, and each prompt states what it expects (for example `(y/n)` or `HH:MM`).

## Interaction Model and Command Structure

The shell is a **guided, numbered-menu** interface. It holds one in-memory session (the current configuration plus any generated schedules) for the whole run.

```
1. Configuration               -> Faculty, Courses, Rooms, Labs, Time Slots,
                                  Class Meeting Patterns, Meetings, Global Settings
2. Run Scheduler
3. View / Export Schedules
4. Config File (new / load / save / print / validate)
0. Exit
```

Each entity menu offers **Add / Modify / Delete / View**. Time Slots also offers global timing options (max gap / min overlap), and Global Settings covers the generation limit and optimizer flags.

Equivalent typed commands are also accepted at the main menu, in the form `<area> <action>`:

| Command | Actions |
|---|---|
| `faculty` | `add`, `modify`, `delete`, `view` |
| `course`, `lab`, `room`, `pattern`, `meeting` | `add`, `modify`, `delete` |
| `timeslot` | `add`, `modify`, `delete`, `timing` |
| `settings` | `limit N`, `limit --reset`, `enable-flag F`, `disable-flag F` |
| `config` | `new`, `print`, `load <path>`, `save [path]`, `validate` |
| `schedule` | `generate [--limit N]`, `summary`, `view <index>`, `clear`, `export <json\|csv> <path> [--index N] [--overwrite]` |

## Configurations: Create, Load, Validate, Save

From **Main menu -> 4. Config File** (or the `config` commands):

- **New:** starts a fresh configuration seeded with one placeholder room, course, faculty member, and class pattern (the library does not accept a completely empty configuration). Edit or delete the placeholders as you build real data.
- **Load:** reads and validates a JSON file. Leaving the path blank loads the example config.
- **Validate:** re-checks the entire current configuration and reports whether it is valid.
- **Save:** writes the configuration as JSON. Leaving the path blank reuses the last loaded or saved path.
- **Print:** shows the current configuration as JSON.

The shell tracks unsaved changes and offers to save before you exit, start a new configuration, or load another one.

## Generating and Exporting Schedules

1. **Main menu -> 2. Run Scheduler.** Enter a generation limit, or leave it blank to use the configuration's own limit. Large limits can take a while to solve, so try a small number first.
2. The result is one of: success, no feasible schedule, invalid configuration, or a solver error. Each is reported with its own message.
3. **Main menu -> 3. View / Export Schedules** lets you see a summary, view one schedule by index, clear results, or export.
4. **Export** takes a format (`json` or `csv`), an output path, and an optional schedule index (blank exports all schedules). An existing file is never overwritten unless you confirm overwrite (`--overwrite` on the command line).

## Invalid Data and Referenced-Item Deletion

**Invalid data.** Numeric and time prompts re-ask or reject bad input instead of crashing. Every add, modify, and delete runs inside the library's edit mode, which re-validates the *complete* configuration. If the edit would make it invalid, the change is rolled back, the previous valid configuration stays intact, and a message names the affected area (for example `Could not save changes, previous version kept: ...`). A failed load likewise leaves the current configuration untouched.

**Referenced items.** Deleting a room, lab, or faculty member that a course still references is blocked, and the message lists the courses that reference it. Deleting the last section of a course is blocked while other courses list it as a conflict or a faculty member lists it as a preference. Other safeguards: the last time block on a weekday and the last meeting in a class pattern cannot be deleted. Every delete asks for confirmation first.

## Example Session

```
$ uv run python main.py
Loaded example configuration from 'app/examples/config_example.json'.

Select: 1                       # Configuration
Select: 3                       # Rooms
Select: 1                       # Add Room
Enter the room's name: Roddy 150
Enter the room's max student capacity: 30
  Features this room provides (comma-separated, blank for none):
  Restrict this room's availability? (y/n, default n = available any time): n
Room added.

Select: 3                       # Delete Room
What is the name of the room you want to remove? Roddy 136
Cannot delete 'Roddy 136': still referenced by CMSC 140, CMSC 140, ...
 -- remove this room from those courses first.

Select: 0 / 0                   # back to main menu
Select: 2                       # Run Scheduler
Schedule generation limit (blank = use config's limit): 3
Generated 3 schedule(s).

Select: 3 / 3                   # View / Export -> Export
Format (json/csv): csv
Output file path: schedules.csv
Export a single index, or blank for all:
Overwrite if it exists? (y/n): n
Exported to '/.../schedules.csv'.

Select: 0 / 4 / 3               # Config File -> Save
Path to save to (blank = reuse last path): my_config.json
Saved configuration to 'my_config.json'.
```
