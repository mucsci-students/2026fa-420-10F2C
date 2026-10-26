# 2026fa-420-10F2C — Course Scheduler

A web application for building, validating and solving university course-scheduling configurations, with a web GUI organized into three modes: **Configuration Editor**, **Schedule Generator** and **Schedule Viewer**. It is built on the [`course-constraint-scheduler`](https://github.com/mucsci/scheduler) library, which uses the Z3 solver to find schedules that satisfy every hard constraint (faculty availability, room and lab capacity, course conflicts, meeting patterns).

The Sprint 1 command-line shell is still included and shares the same model code (see [Command-line shell](#command-line-shell-sprint-1)).

**Contributors:** Calvin Becker, Alan Reider, Henry Malesker, Joseph Lucks, Samsong Tamang, James Liranzo

## Contents

- [Install and start](#install-and-start)
- [The three modes](#the-three-modes)
- [Representative workflow](#representative-workflow)
- [Configuration Editor](#configuration-editor)
- [Schedule Generator](#schedule-generator)
- [Schedule Viewer](#schedule-viewer)
- [AI Assistant](#ai-assistant)
- [Behavior shared by every page](#behavior-shared-by-every-page)
- [Architecture (MVC)](#architecture-mvc)
- [Running the tests](#running-the-tests)
- [Command-line shell (Sprint 1)](#command-line-shell-sprint-1)
- [Developer reference](#developer-reference)

## Install and start

**Prerequisites:** [uv](https://docs.astral.sh/uv/) and Git. The project requires Python 3.14 (`pyproject.toml`, `.python-version`); if it isn't installed, `uv` downloads it automatically.

```bash
# install uv if you don't have it (it is not preinstalled on the department Arch machines)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

git clone https://github.com/mucsci-students/2026fa-420-10F2C.git
cd 2026fa-420-10F2C
uv sync                                  # creates .venv and installs pinned dependencies
uv run python manage.py runserver        # starts the web GUI
```

Then open **http://127.0.0.1:8000/** in a browser. Run every command from the repository root.

- No database and no migrations are needed. Each browser gets its own in-memory session (configuration plus schedules); it is lost when the server stops, so **save** your configuration and **export** schedules you want to keep.
- A new browser session starts with the example configuration (`app/examples/config_example.json`) loaded, so every page has data to explore immediately.
- To reach the server from another machine (for example when working over SSH), run `uv run python manage.py runserver 0.0.0.0:8000` and browse to that host's address on port 8000.
- Running plain `python manage.py ...` without `uv run` fails with `ModuleNotFoundError`: the dependencies live in `.venv`.

## The three modes

Every page has the same navigation bar with links to **Home**, **Configuration Editor**, **Schedule Generator** and **Schedule Viewer**, a status indicator for the configuration (**none loaded**, **Unsaved changes**, or **no unsaved changes**), and a **Dark mode** toggle.

| Mode | What it is for |
|---|---|
| **Configuration Editor** | Create, load, edit, validate and save a scheduler configuration. Eight areas: Time Slots, Rooms, Labs, Courses, Faculty, Class Patterns, Meetings, Global Settings. |
| **Schedule Generator** | Pick a configuration, optionally override the limit or optimizer flags for one run, and generate schedules. |
| **Schedule Viewer** | Browse generated or loaded schedules, load schedules from a file, export them as JSON or CSV, and clear them. |

## Representative workflow

This walk-through touches all three modes, starting from a fresh browser session (the example configuration is already loaded).

1. **Configuration Editor → Rooms → Add room.** Enter `Roddy 150`, capacity `30`. The room appears in the list and the navigation bar now shows **Unsaved changes**.
2. **Configuration Editor → Rooms**, try to delete `Roddy 136`. Its **Delete** button is disabled, and the row lists the courses that still use the room. Remove the room from those courses first, or leave it.
3. **Configuration Editor → Global Settings.** Set the generation limit to `5`, tick `pack_rooms`, and click **Save settings**. The page confirms each change.
4. **Configuration Editor → Validate configuration.** "Configuration is valid" appears. Click **Save configuration**; the browser downloads the JSON file and the status returns to **no unsaved changes**.
5. **Schedule Generator.** Leave the one-run fields alone (or change them — they never alter the saved configuration) and click **Generate schedules**. The button shows a busy state, and on success you land in the Schedule Viewer.
6. **Schedule Viewer.** Step through the schedules with **Previous** / **Next**, and switch between the course, room and faculty views.
7. **Schedule Viewer → Export → Export All Schedules (JSON).** The file downloads.
8. **Schedule Viewer → Clear schedules**, confirm. Then **Load schedules from a file** with the JSON from step 7: the same schedules come back without running the solver again.

## Configuration Editor

### Configuration lifecycle

The editor home page shows the current configuration (file name, unsaved-changes state, how many items each area holds) and four actions:

- **New configuration** starts a fresh configuration seeded with one placeholder room, course, faculty member and class pattern. The scheduler library does not accept a completely empty configuration, so edit or replace the placeholders as you add real data.
- **Load configuration** uploads a JSON file and validates it completely before replacing anything. If the file is not valid JSON or is not a valid configuration, the problems are listed under the file field and the current configuration is kept exactly as it was.
- **Save configuration** validates, then downloads the configuration as JSON (named after the file it was loaded from, or `scheduler_config.json`). It is serialized through the library's own Pydantic model.
- **Validate configuration** re-checks the entire configuration through the library and lists any problems.

**Unsaved-changes protection.** Any successful edit marks the configuration as having unsaved changes. Before **New** or **Load** would discard unsaved changes or loaded schedules, the form says exactly what will be lost and requires you to tick a confirmation box. Saving clears the flag.

### Configuration areas

Every area offers add, edit and delete, with forms that label each field and mark the required ones.

| Area | What you edit |
|---|---|
| **Time Slots** | Time blocks per weekday (start, end, spacing between start times), plus the global timing options *Maximum time gap* and *Minimum time overlap* (minutes). |
| **Rooms** / **Labs** | Name, capacity, features. |
| **Courses** | Course ID, credits, capacity, candidate rooms and labs, conflicts, eligible faculty. |
| **Faculty** | Name, credit limits, unique-course limit, available times, mandatory and maximum days, course/room/lab preferences. |
| **Class Patterns** | Credits, optional fixed start time, enabled. Patterns have no name, so they are numbered by position. A new pattern needs one meeting, so the Add form takes the first. |
| **Meetings** | Day, duration, lab meeting, delivery mode, optional start time, on any pattern. |
| **Global Settings** | Saved generation limit (a positive whole number; **Reset limit to default** sets it to 10) and the seven optimizer flags, each with a plain-language description shown under the checkbox and as a tooltip. |

### Invalid data

Every add, edit and delete runs through the library's edit mode, which re-validates the **whole** configuration on a copy. If the change would make the configuration invalid, it is rejected, the error appears on the form next to the field or area it concerns, and the configuration stays exactly as it was. A meeting longer than every time block on its day is accepted with a warning that schedules needing it may not be feasible.

### Deleting and renaming referenced items

Rooms, labs, faculty, courses and class patterns are linked to each other by name, so deleting one can leave other
records pointing at nothing. Instead of blocking the delete, every one of them works the same way: **Delete** is
always available and opens a review page that says what else will change, asks you to confirm anything that
removes more than the item itself, and then does everything as ONE validated change. If any part is rejected,
nothing is removed and the page tells you why. The page lists the affected records and notes that the whole thing
can be undone (see [Undo, redo and history](#undo-redo-and-history)).

**A delete never puts a different record in the deleted one's place.** If you delete the lab "Mac", the lab
"Linux" does not take over its course sections; the references to "Mac" are simply removed. A section that would
be left with nothing it can use is deleted too, but only after you tick a box that says so.

| Deleting a... | ...is removed from | Also deletes course sections when |
| --- | --- | --- |
| **Room** | course room lists, faculty room preferences | a section lists only this room (it could not be scheduled without one) |
| **Lab** | course lab lists, faculty lab preferences | never: a section that listed only this lab is left without one, and the page says so |
| **Faculty member** | course faculty assignments, their own preferences | nobody else could teach the section: they were its only assignee and nobody else prefers the course, or they are the only one who prefers a course with no assigned person. A section that assigned only them, where someone else prefers the course, goes back to "the scheduler chooses" |
| **Course** (its last section) | other courses' conflict lists, faculty course preferences | never |
| **Class pattern** | nothing | it is the only enabled pattern for its credit value (the sections with that many credits could not be scheduled any more) |

- **One tick-box.** When course sections would be deleted too, the page lists them and shows a box ("I understand
  this also deletes 3 course sections ..."). Without the tick nothing is deleted and the page explains why.
- **Label only.** The page names the item being deleted and nothing more (no extra capacity or credit details).
- **Used by.** The Rooms, Labs, Faculty, Courses and Class Patterns lists show, for each row, what depends on it
  (for example "9 courses", "only candidate for 2 sections"), folded into a details control.
- **Other guards.** A configuration always keeps at least one room, course and faculty member, so the last of
  each cannot be deleted. The last time block on a weekday and the only meeting in a pattern cannot be deleted.
  If the library still rejects the combined result (for example a lab-less section it does not accept), nothing
  changes and the page shows the library's reason.
- **Confirmation.** Every delete asks for confirmation first, and Cancel changes nothing.
- **Renames propagate.** Renaming a room, lab, faculty member or course updates every reference to it in the same
  validated step, and says how many it updated.

### Undo, redo and history

Every successful change in the Configuration Editor can be undone, including a delete that cascaded through many
courses and faculty preferences.

- **Where to find it.** After a change, the "saved" message carries an **Undo** button right where you are
  looking. The **Undo** and **Redo** buttons at the top of every Configuration Editor page name the change they
  will reverse (for example "Undo: Delete room 'Roddy 136'"); the bar only appears once there is something to undo
  or redo. **Ctrl+Z** presses Undo and **Ctrl+Y** (or Ctrl+Shift+Z) presses Redo (Cmd on a Mac), except while you
  are typing in a field.
- **History page.** **History** lists every remembered change, newest first, with when it happened and what it
  changed ("Removed room Roddy 136; Changed 14 courses; Changed 9 faculty members"). **Go back to before this**
  returns to how things were just before any entry in one step; the later changes are kept so they can be redone.
- **How it works.** Undo and redo use the Memento design pattern (see [Design patterns](#design-patterns)). Just
  before each edit the configuration saves a memento of each part of itself (rooms, labs, courses, faculty, class
  patterns, time slots, global settings); after the edit only the parts that really changed are kept. Undo puts
  those parts back as one step, so a cascade is reversed completely, never partly. Redo re-applies it. Making a
  new change after an undo clears redo.
- **Safe with several tabs.** Every Undo, Redo and "go back" button carries a version number of the configuration
  it was drawn from. If the configuration has changed since (another tab, a double click), the request is refused
  with an explanation instead of undoing something you did not see.
- **Unsaved changes.** Undoing back to the state you loaded or saved clears the "Unsaved changes" indicator. After
  you save, undoing an older change marks the configuration as unsaved again, because the saved file still contains it.
- **Restore previous configuration.** Starting a new configuration, loading a file or switching to a saved one
  still asks before discarding unsaved work, but the replaced configuration (with its edits, undo history and
  schedules) is kept for the rest of the session. The Configuration Editor shows **Restore previous
  configuration**; restoring swaps the two, so it can be reversed too. Only the one before is kept, and it is lost
  when the server restarts.
- **Schedules and changes.** Generated schedules are not changed by undo or redo, and editing the configuration
  does not delete them. Instead the Schedule Viewer and Generator say "These schedules are out of date. They were
  generated from an earlier version of the configuration" for as long as that is true; undoing back to the
  configuration they came from makes the notice go away. Schedules imported from a file are never flagged, because
  their origin is unknown.
- **Limits.** The newest 25 changes are remembered. History is kept in memory only, so it is lost when the server
  restarts.
- **Where the code is (MVC).** Model: `app/memento.py` (the mementos), `app/history.py` (the undo and redo stacks,
  versions), the hooks in
  `app/commands/common.py` (`apply_session_edit`) and `app/session.py` (restore previous, schedule versions).
  Controller: `gui/controllers/dependencies.py` (how the records depend on each other, shared by every delete),
  `gui/controllers/history_controller.py`. View: `gui/views_delete.py` (the one delete flow),
  `gui/views_history.py`, `gui/templates/gui/components/cascade_delete.html`, `history_bar.html`,
  `gui/templates/gui/history.html` and `gui/static/gui/js/history.js`.

## Schedule Generator

1. **Configuration to run.** Configurations you load or save in this browser session are kept as snapshots. Pick one from the selector to make it the active configuration. Switching clears schedules generated from the previous configuration, so save unsaved edits first.
2. **One-run overrides (optional).** A generation limit and a set of optimizer flags that apply **to this run only**. They never change the saved configuration; to change the saved values, use **Configuration Editor → Global Settings**. The flag checkboxes start with the configuration's saved flags ticked.
3. **Generate schedules.** Generation runs in the background and the page shows a **progress bar** with the number of schedules found out of the limit (for example "Found 3 of 10 schedules (30%) · 12s elapsed") and the elapsed time. The bar moves when a schedule is found, so it can stay empty while the solver works on the first one; with no limit it is indeterminate. **Cancel generation** stops the run once the solver finishes the schedule it is working on, and your previous schedules are kept. While a run is going the button is disabled and a second run in the same session is refused until the first finishes; if you reload the page the progress bar picks up where the run is. Without JavaScript the form still works: the page waits for the run to finish and then shows the result, without the progress bar.

The result is always one of:

| Outcome | What you see |
|---|---|
| Success | "Generated N schedule(s)." and the Schedule Viewer opens with the new results. |
| No feasible schedule | A warning that no schedule satisfies every hard constraint. Previous results are cleared. |
| Invalid configuration | The library's reason the configuration can't be scheduled. Previous results are kept. |
| Invalid override | The bad field (a limit that isn't a positive whole number, an unknown flag) is marked on the form. Nothing runs. |
| Cancelled | "Generation was cancelled." Nothing is saved; previous results are kept. |
| Unexpected error | "Schedule generation failed unexpectedly" with the reason. Previous results are kept. |

Large limits can take a long time to solve; try a small number first.

## Schedule Viewer

<!-- The navigation and view-mode bullets below describe feature/schedule_view; keep them in step with that branch as it merges. -->

The viewer shows whatever schedules are currently available, whether generated or loaded from a file.

- **Navigation.** The page shows how many schedules are available and which one you are viewing. **Previous** and **Next** step through them (they are disabled at either end), and `?schedule=N` in the address links straight to one.
- **Views.** One schedule at a time as a weekly overview, in three views:
  - **Course** — each meeting labelled by course section.
  - **Room** — grouped by room and lab; lab meetings appear under the lab, other meetings under the room.
  - **Faculty** — grouped by faculty member.

### Loading schedules

**Load schedules from a file**: choose a `.json` file and click **Load schedules**.

- The whole file is checked before anything changes. If it is not valid JSON, is a configuration file, or has an invalid entry, up to five specific problems (each naming the schedule and course) appear under the file field and the current schedules stay as they were.
- A file that isn't a schedule file at all is reported as "This is not a supported schedule format", with a hint such as "Load it from the Configuration Editor instead." for configuration files.
- If schedules are already loaded, you must tick **Replace the N schedule(s) currently loaded** first.
- Loaded schedules don't need a configuration, and the solver does not rerun.

### Exporting schedules

| Button | Downloads |
|---|---|
| **Export This Schedule (JSON)** | The selected schedule (the one you are viewing is preselected), as `schedule-<n>.json` |
| **Export This Schedule (CSV)** | The same schedule as `schedule-<n>.csv` |
| **Export All Schedules (JSON)** | Every available schedule in one file, `schedules-all-<count>.json` |
| **Export All Schedules (CSV)** | Every available schedule in one file, `schedules-all-<count>.csv` |

- **JSON** uses the format below, so a single schedule or the whole set can be loaded back later.
- **CSV** is for spreadsheets: one row per meeting with the columns `schedule, course, faculty, room, lab, day, start, end, duration_minutes, lab_meeting`. A section with no meetings (for example an online course) gets one row with blank meeting columns. CSV can't be loaded back into the viewer; use JSON for that.
- Export buttons are disabled until there are schedules. Exporting never changes the loaded schedules.
- **Overwrite protection:** exports (and configuration saves) are browser downloads. The browser decides where the file goes and asks before replacing an existing file, or renames the new one. The application never writes to a path on your computer, so it cannot overwrite your files.

### Clearing schedules

**Clear schedules** removes every schedule from the viewer, generated or loaded. It always asks first ("Remove all N schedules from the viewer? This cannot be undone."). Only the schedules are removed; the configuration stays loaded. The button is disabled with "Nothing to clear yet." when there are no schedules.

### Schedule JSON format (version 1)

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
- `faculty`, `room` and `lab` are names or `null`. `meetings` may be empty (for example an online course).
- `day` is `MON`–`FRI`; times are 24-hour `HH:MM`. A meeting needs `duration` (minutes) or `end`; if both are given, `duration` is used.
- Also accepted: a single schedule (just the list of assignments); a bare list of schedules, as written by the scheduler library's `JSONWriter` (where `meetings` may be called `times`); and meetings written as `"MON 09:00-09:50"`.
- Rejected: a `version` newer than 1, a different `format` value, and files over 5 MB.

## AI Assistant

Click the round chat button in the bottom-right corner of any page and type a request in everyday language. Hover the button and click the small arrow to slide it out of the way; a small tab at the screen edge brings it back. For example:

- "What can you do?"
- "List all rooms", "How many credits is CMSC 420?", "Show me faculty Hogg"
- "Add a room named RODDY150 with capacity 35"
- "Add course CMSC 421 with 3 credits, taught by Hogg in RODDY150"
- "Add a time slot on Friday from 17:00 to 19:00", "Add a class pattern for 3 credits meeting Monday for 150 minutes"

**Setup.** The OpenAI key is read from the `OPENAI_API_KEY` environment variable and never written to a file, a page or a log. The model is `gpt-6-luna` unless `OPENAI_MODEL` is set:

```bash
export OPENAI_API_KEY="your key here"      # never commit it
export OPENAI_MODEL="gpt-6-luna"           # optional; this is the default
uv run python manage.py runserver
```

With no key set, the assistant says so and nothing else changes.

**How a request runs.**
- The AI can only call the tools in `gui/ai/tools.py`, and every tool calls the same controller the normal pages use. Duplicate names, unknown rooms and bad values are rejected the same way the forms reject them, and a rejected change leaves the configuration as it was.
- Your request stays on screen with a **"Working on it…"** status. When the request finishes, the status is replaced by the result, and the chat box takes a new request. If the AI changed the configuration, the top bar shows **Unsaved changes** and the reply has a **Refresh page** button, because the page behind the chat was drawn before the change.
- While a request is running, Send and Enter are ignored, so a double click or a second Enter does nothing. The server also refuses a second request from the same browser until the first one is done, so a change can't be applied twice.
- Each request is sent on its own with the configuration as it is right now, edits you just made by hand included. Earlier chat messages are not sent.
- The reply comes from what the application actually did. A change says **"applied but not yet saved to a file"**: it's in the open configuration and marked as unsaved changes, but it isn't written to disk until you save it.
- AI service errors are retried at most twice, with a 60-second timeout. After that you get a "couldn't finish" message, and nothing is changed.

Tests use a fake AI (`tests/test_ai_chat.py`, `tests/test_ai_tools.py`) or a mocked OpenAI endpoint (`tests/test_ai_langchain.py`), so no key is needed and no API calls are made.

## Behavior shared by every page

### Errors and error pages

- **Problems you can fix** (a value out of range, a file that isn't valid JSON, a change the scheduler rejects) appear on the page you are on, next to the field or form, starting with **"Error:"**. Whatever was loaded before stays as it was.
- **Unexpected problems** show a **"Something went wrong"** page with the normal navigation, what to do next and a short reference code. Nothing is restarted; only the last action may not have been applied. The full technical report, with the same reference code, is printed in the terminal running the server. In development mode (`DEBUG = True`) a folded "Technical details" line shows the error type and message, never a traceback.
- **Pages that don't exist** show a **"Page not found"** page with links to the three modes.

### Empty states

Pages never appear blank. With no configuration loaded, the Configuration Editor and Schedule Generator offer **New Configuration** and **Load Configuration** buttons, and **Generate schedules** is disabled. With no schedules, the Schedule Viewer links to the generator and to loading a file, and Export and Clear are disabled.

### Loading states

While a file loads, saves, validates or generates, the button you pressed changes to a busy label ("Loading…", "Validating…") and a banner with a spinner appears at the top of the page. The form's buttons are greyed out and a second click is ignored. Downloads (Save, Export) stay busy until the file arrives, then the banner says "Download started." Without JavaScript every button still works, just without the busy state.

### Usability and accessibility

- Every action is reachable with the keyboard (Tab / Shift+Tab, Enter, Space); forms use real labels tied to their fields.
- Status never relies on colour alone: the unsaved-changes indicator is text, errors begin with "Error:", disabled actions say why they are disabled.
- Destructive actions (delete, clear, replacing loaded data, starting a new configuration over unsaved work) always ask for confirmation.
- Controls whose purpose isn't obvious, such as the optimizer flags and timing options, have help text and tooltips.
- Light and dark themes; the **Dark mode** toggle remembers your choice in this browser.

## Architecture (MVC)

The GUI follows Model–View–Controller. User actions go through a controller; views never run scheduler workflows themselves, and models never build web responses.

```
 Browser ──HTTP──▶ View (gui/views*.py)          parse the request, pick a form, render a template
                     │  calls
                     ▼
                  Controller (gui/controllers/)  validate the request, run the workflow,
                     │  calls                      raise ControllerError for fixable problems
                     ▼
                  Model (app/ + scheduler lib)   configuration, edits, generation, schedule files
```

| Layer | Where | Responsibility |
|---|---|---|
| **Model** | `app/session.py` | `Session`: the current `CombinedConfig`, available schedules, unsaved-changes flag, saved configuration snapshots. Load/save through the library's Pydantic models. |
| | `app/memento.py`, `app/history.py` | Undo and redo with the Memento pattern: one memento class per kind of configuration item, and the history that keeps them (see [Design patterns](#design-patterns)). |
| | `app/crud.py` | `apply_edit()`: every configuration change runs inside the library's `edit_mode()`, so only a fully valid configuration is ever stored. |
| | `app/schedule_ops.py` | Schedule generation through `Scheduler`, reported as a `GenerationOutcome`. |
| | `app/schedule_io.py` | Neutral schedule records (`Assignment`, `MeetingTime`) used by both generated and loaded schedules; JSON/CSV reading, writing and validation. |
| | `course-constraint-scheduler` | The configuration models, validation rules and Z3 solver. Validation is never reimplemented in this project. |
| **Controller** | `gui/controllers/` | One module per area: `config_controller.py` (lifecycle), `timeslots.py`, `rooms.py`, `labs.py`, `courses.py`, `faculty.py`, `patterns.py`, `meetings.py`, `settings.py`, `schedule_controller.py` (generate, load, export, clear). `errors.py` defines `ControllerError` / `FieldError`; `uploads.py` reads uploaded files safely. Controllers return plain data and never touch templates or `HttpResponse`. |
| **View** | `gui/views.py`, `gui/views_*.py` | Thin request handlers: call a controller, then redirect with a message or re-render the form with its errors. `views_errors.py` renders the error pages. |
| | `gui/templates/gui/` | Pages and shared components (`components/`), including `base.html` (navigation, status, loading banner). |
| | `gui/forms.py` | Django forms: field types, labels, help text, confirmation checkboxes. |
| | `gui/static/gui/` | CSS and JavaScript (`loading.js` for busy states, `theme.js` for dark mode). |
| **AI** | `gui/ai/` | `tools.py`: the fixed tool set (each tool has a Pydantic argument schema and calls a controller); `service.py`: one request (duplicate guard, reply built from tool results); `runner.py`: the LangChain agent; `prompt.py`: base prompt. `gui/views_ai.py` is the endpoint the chat button posts to; the button itself is `templates/gui/components/chat_widget.html` with `static/gui/js/chat.js`. |
| **Glue** | `gui/session_store.py` | Gives each browser its own `Session` (keyed by an id in a signed-cookie session). |
| | `gui/middleware.py` | Turns unexpected exceptions into the friendly error page and logs the traceback. |
| | `config/` | Django settings and root URL configuration; `gui/urls.py` maps each URL to a view. |

The Sprint 1 shell (`app/shell.py`, `app/commands/`) uses the same Model layer, which is why both interfaces validate and save configurations identically.

### Design patterns

MVC (above) is one of the patterns used. The others are described here as they are added.

#### Memento (undo and redo)

- **Problem.** Every configuration edit must be undoable and redoable, including a delete that changes rooms, courses
  and faculty at once, without the history having to know how each kind of item is stored.
- **Where.** `app/memento.py` (the pattern), `app/history.py` (the caretaker), `app/commands/common.py`
  (`apply_session_edit`, where an edit is wrapped), `gui/controllers/history_controller.py` (what the buttons call).
- **Participants.**
  - *Originator*: `ConfigOriginator` creates mementos from the loaded configuration and restores it from them.
  - *Memento*: the abstract `Memento` and one concrete class per kind of item, `RoomsMemento`, `LabsMemento`,
    `CoursesMemento`, `FacultyMemento`, `PatternsMemento` (which carries each pattern's meetings), `TimeSlotsMemento`
    and `SettingsMemento`. Each knows how to read and write only its own part of the configuration, and how to
    describe a change to it in words.
  - *Composite*: `CompositeMemento` holds the mementos of several parts, so a cascading delete is still one step.
  - *Caretaker*: `ConfigHistory` keeps the undo and redo stacks of composite mementos. It never looks inside them.
- **How they interact.** `apply_session_edit` asks the history to `capture()` (the originator saves a memento of every
  part) and runs the edit. If the library accepts it, `record()` keeps only the mementos whose part changed. On Undo
  the caretaker has the originator save the parts it is about to replace (for Redo), then `restore()` puts the old
  parts back through the library's edit mode, which validates the whole result and changes nothing if it is refused.
- **Why it fits.** The state is saved and restored without the caretaker (or any page) knowing how it is stored, so
  encapsulation is kept; and because each kind of item has its own memento, an edit to one room saves one slice of
  the configuration rather than a copy of everything.

## Running the tests

```bash
uv run pytest            # whole suite
uv run pytest tests/test_gui_rooms_labs.py -q   # one file
```

The tests live in `tests/`: `test_crud_*` and `test_schedule_*` cover the model and CLI layer, `test_gui_*` cover the controllers and pages through Django's test client.

## Command-line shell (Sprint 1)

```bash
uv run python main.py
```

A numbered-menu interface over the same model code: configuration CRUD for every area, generate, view and export schedules, and new/load/save/validate. Type `help` at any menu prompt for that screen's options; `0` goes back. The web GUI is the Sprint 2 interface; the shell is kept for reference.

## Developer reference

Shared building blocks — use these instead of rewriting them per feature:

| Need | Use | Where |
|---|---|---|
| Apply a configuration change safely | `apply_edit()` via the controller helpers in `gui/controllers/common.py` | `app/crud.py` |
| Read the session's schedules (generated or loaded) as rows | `get_schedule(request, i)`, `get_schedules(request)`, `schedule_count(request)` | `gui/controllers/schedule_controller.py` |
| Store new results (generate, load, clear) | `replace_schedules(request, schedules)` | same |
| One schedule row: course, faculty, room, lab, meetings | `Assignment`, `MeetingTime` | `app/schedule_io.py` |
| Write schedules as JSON / CSV | `schedules_to_json(...)`, `schedules_to_csv(...)` | same |
| Build a download (one schedule or all, JSON or CSV) | `export_schedules(request, index_or_None, "json"\|"csv")` → `ExportFile` | `gui/controllers/schedule_controller.py` |
| Read an uploaded file (empty/unreadable/too large handled) | `read_upload(uploaded_file, "field_name")` | `gui/controllers/uploads.py` |
| Report a fixable problem on a form | `raise ControllerError([FieldError("field", "message")])` | `gui/controllers/errors.py` |
| "Tick to confirm" before replacing or discarding data | `ConfirmReplaceMixin` + `require_confirmation(...)` | `gui/forms.py` |
| Send a file download | `download_response(filename, content, content_type, download_token(request))` | `gui/views.py` |
| Show a loading state on submit (and ignore double clicks) | `<form ... data-loading="Generating schedules…">`, plus `data-loading-download` for downloads | `gui/static/gui/js/loading.js` |
| Render a whole form (errors + every field) | `{% include "gui/components/form_fields.html" with form=my_form %}` | `gui/templates/gui/components/` |
| "No configuration" actions on an empty page | `{% include "gui/components/no_config_actions.html" %}` | same |
