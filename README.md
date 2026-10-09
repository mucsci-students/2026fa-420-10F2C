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

## Loading and Exporting Schedules (Schedule Viewer)
## Error Messages and Error Pages (all modes)

Problems are always shown inside the app, never only in the terminal:

- **Problems you can fix** (a value out of range, a file that isn't valid JSON, a change the scheduler rejects) appear on the page you're on, next to the field or form, starting with **"Error:"**. Whatever was loaded before stays as it was. For example, a failed schedule import keeps the schedules already in the Viewer.
- **Unexpected problems** (a bug) show a **"Something went wrong"** page with the usual navigation, what to do next, and a short reference code. Nothing is restarted, so you can go back and keep working; only the last action may not have been applied. The full technical report, with the same reference code, is printed in the terminal running the server. In development mode (`DEBUG = True`) a folded "Technical details" line on the page shows the error type and message, but never a traceback.
- **Pages that don't exist** (an old link, a removed item) show a friendly **"Page not found"** page with links to the three modes.

Code: `gui/middleware.py` (catches unexpected errors and logs them), `gui/views_errors.py` and `gui/templates/gui/error.html` / `not_found.html` (the pages); `config/urls.py` sets them as Django's `handler404` / `handler500`.

## Class Patterns and Meetings (Configuration Editor)

**Configuration Editor -> Class Patterns** and **-> Meetings** manage `time_slot_config.classes`. Patterns have no name, so they are numbered by position.

- **Class patterns:** add, edit (credits, optional fixed start time, enabled) and delete. A new pattern needs one meeting, so the Add form takes the first; editing a pattern keeps its meetings.
- **Meetings:** add, edit and delete a meeting on any pattern (day, duration, lab, delivery mode, optional start time). A pattern's **only meeting cannot be deleted** (delete the pattern instead).
- **Invalid data:** every change re-validates the whole configuration. A rejected change shows what is wrong on the form and leaves the configuration as it was.
- **Deletion:** nothing in the configuration points at a pattern by name, so there is no reference list. Deleting a pattern asks for confirmation and lists the meetings it removes; if a course would be left with no usable pattern, the scheduler rejects the change and nothing is removed.
- **Fit warning:** a meeting longer than every time block on its day is accepted, with a warning that schedules needing it may not be feasible.

Code: `gui/controllers/patterns.py` and `gui/controllers/meetings.py` (Controller), `gui/views_patterns.py` and `gui/views_meetings.py` (View), `gui/forms.py` (forms).

## Selecting a Saved Configuration for Generation

The Schedule Generator keeps validated configurations that you load or save in the current browser session. Use the **Configuration to run** selector to switch between those saved snapshots before generating schedules. Selecting a snapshot restores it as the active configuration and clears schedules generated from the previous configuration; unsaved edits should be saved first if they need to be retained.

## Global Settings (Configuration Editor)

**Configuration Editor -> Global Settings** edits the saved generation limit and optimizer flags.

- **Generation limit:** a positive whole number. **Reset limit to default** puts it back to 10. The limit can't be removed, because every configuration has one.
- **Optimizer flags:** one checkbox per flag the scheduler library supports. Ticked flags are enabled; unticking a flag disables it. Each flag has a short plain-language description under its checkbox, which also appears as a tooltip when you hover over or focus it (for example, `pack_rooms`: "Try to use rooms back to back..."). The Schedule Generator's one-run flag checkboxes show the same descriptions. Descriptions live in `gui/constants.py` (`OPTIMIZER_FLAG_HELP`) and follow the scheduler library's own definitions. **Save settings** applies the limit and the flags together and reports each change ("Generation limit set to 50.", "Optimizer flag 'pack_labs' added.").
- **Invalid data:** a limit of zero or less is rejected on the form, and a rejected change leaves the configuration as it was.
- **Deletion:** nothing refers to these settings, so there are no references to block. "Deleting" a setting means unticking a flag or resetting the limit, and both are always allowed.
- **Saved vs. one-run:** these are saved with the configuration. The Schedule Generator's one-run overrides never change them.

Code: `gui/controllers/settings.py` (Controller), `gui/views_settings.py` (View), `gui/forms.py` (`GlobalSettingsForm`).

## Loading States (all modes)

While a file is loading or saving, the app shows that it is busy instead of looking frozen:

- The button you pressed changes to **"Loading…"** (**"Validating…"** for Validate configuration), and a banner with a spinner appears at the top of the page. The form's buttons are greyed out and a second click is ignored, so a duplicate request can't be sent.
- **Load configuration**, **Start new configuration**, **Validate** and **Load schedules** stay busy until the server answers. The next page, with its success or error message, replaces the loading state.
- **Save configuration** and the **Export** buttons are downloads, which don't load a new page. They stay busy until the file arrives, and the banner then says "Download started." If something goes wrong, the error page or message replaces the loading state instead.
- Without JavaScript every button still works; there is just no loading state.

How it works: `gui/static/gui/js/loading.js` (loaded by `gui/templates/gui/base.html`, which also holds the `#loading-status` banner) acts on any form with `data-loading="Message"`. For downloads (`data-loading-download`) it sends a random `download_token`, and `download_response()` in `gui/views.py` sends it back in a short-lived cookie with the file, which tells the page the download has finished.

## Loading Schedules (Schedule Viewer)

**Schedule Viewer -> Load schedules from a file**: choose a `.json` file and click **Load schedules**.

- The whole file is checked before anything changes. If it is not valid JSON, is a configuration file instead of a schedule file, or has an invalid entry, the errors appear under the file field (up to five specific problems, each naming the schedule and course), and the schedules already loaded stay as they were.
- A file that isn't a schedule file at all (a configuration file, a different `format`, or JSON with no schedules) is reported as "This is not a supported schedule format", with a hint such as "Load it from the Configuration Editor instead." for configuration files.
- If schedules are already loaded, you must tick **Replace the N schedule(s) currently loaded** first.
- Loaded schedules don't need a configuration, and the scheduler doesn't rerun.

### Exporting schedules (JSON and CSV)

**Schedule Viewer -> Export** has two rows of buttons:

| Button | Downloads |
|---|---|
| **Export This Schedule (JSON)** | The schedule picked in the list (the one you are viewing is preselected), as `schedule-<n>.json` |
| **Export This Schedule (CSV)** | The same schedule as `schedule-<n>.csv` |
| **Export All Schedules (JSON)** | Every available schedule in one file, `schedules-all-<count>.json` |
| **Export All Schedules (CSV)** | Every available schedule in one file, `schedules-all-<count>.csv` |

- **JSON** uses the format below, so a single schedule or the whole set can be loaded back into the viewer later without rerunning the scheduler.
- **CSV** (the Sprint 1 export) is for spreadsheets: one row per meeting with the columns `schedule, course, faculty, room, lab, day, start, end, duration_minutes, lab_meeting`. A section with no meetings (for example an online course) gets one row with blank meeting columns. The `schedule` column keeps the number shown in the viewer. CSV files can't be loaded back into the viewer; use JSON for that.
- Export buttons are disabled until schedules are generated or loaded. Exporting never changes the loaded schedules.

**Overwrite protection:** exports are browser downloads. Your browser chooses where the file goes and asks before replacing an existing file (or renames the new one). The application never writes to a path on your computer, so it cannot overwrite your files.

### Clearing schedules

**Schedule Viewer -> Clear schedules** removes every schedule from the viewer (generated or loaded).

- It always asks first: "Remove all N schedules from the viewer? This cannot be undone." **Clear schedules** removes them; **Cancel** keeps them. Export them first if you want to keep a copy.
- The button is disabled, with "Nothing to clear yet.", when there are no schedules.
- Only the schedules are removed. The configuration stays loaded.

Code: `clear_schedules()` in `gui/controllers/schedule_controller.py` (Controller), `schedule_clear` in `gui/views.py` and `gui/templates/gui/schedules_clear.html` (View).

### Supported schedule JSON format (version 1)

```json
{
  "format": "course-scheduler-schedules",
  "version": 1,
  "schedule_count": 1,
  "schedules": [
    [
      {
        "course": "CMSC 140.01",
        "faculty": "Hogg",
        "room": "Roddy 136",
        "lab": null,
        "meetings": [
          {"day": "MON", "start": "09:00", "end": "09:50", "duration": 50, "lab": false}
        ]
      }
    ]
  ]
}
```

- `schedules` is a list of schedules; each schedule is a list of course assignments.
- `faculty`, `room`, and `lab` are names or `null`. `meetings` may be empty (for example, an online course).
- `day` is `MON`-`FRI`; times are 24-hour `HH:MM`. A meeting needs `duration` (minutes) or `end`; if both are given, `duration` is used.
- Also accepted: **a single schedule** (just the list of assignments), **a bare list of schedules** (the scheduler library's `JSONWriter` output, where `meetings` may be called `times`), and meetings written as `"MON 09:00-09:50"`.
- Rejected: a `version` newer than 1, a different `format` value, and files over 5 MB.

Code: `app/schedule_io.py` (Model: format and validation), `gui/controllers/schedule_controller.py` (Controller), `gui/views.py` + `gui/templates/gui/schedule_viewer.html` (View).

### Shared building blocks (for developers)

Use these instead of rewriting them in each feature:

| Need | Use | Where |
|---|---|---|
| Read the schedules in the session (generated or loaded) as rows | `get_schedule(request, i)`, `get_schedules(request)`, `schedule_count(request)` | `gui/controllers/schedule_controller.py` |
| Store new results (generate, load, clear) | `replace_schedules(request, schedules)` | same |
| One schedule row: course, faculty, room, lab, meetings | `Assignment`, `MeetingTime` | `app/schedule_io.py` |
| Write schedules as JSON / CSV | `schedules_to_json(...)`, `schedules_to_csv(...)` | same |
| Build a download (one schedule or all, JSON or CSV) | `export_schedules(request, index_or_None, "json"\|"csv")` -> `ExportFile` | `gui/controllers/schedule_controller.py` |
| Show a loading state while a form submits (and ignore double clicks) | `<form ... data-loading="Generating schedules…">`; add `data-loading-download` if the answer is a file download, and pass `download_token(request)` to `download_response(...)` | `gui/static/gui/js/loading.js`, `gui/views.py` |
| Export schedules as a JSON file (one, or all with `index=None`) | `export_schedule_json(request, index)` returns an `ExportFile` for `download_response` | `gui/controllers/schedule_controller.py` |
| Read an uploaded file (empty/unreadable/too large handled) | `read_upload(uploaded_file, "field_name")` | `gui/controllers/uploads.py` |
| "Tick to confirm" before replacing or discarding data | `ConfirmReplaceMixin` + `require_confirmation(...)` | `gui/forms.py` |
| Send a file download (overwrite-safe save/export) | `download_response(filename, content, content_type)` | `gui/views.py` |
| Render a whole form (errors + every field) | `{% include "gui/components/form_fields.html" with form=my_form %}` | `gui/templates/gui/components/` |
