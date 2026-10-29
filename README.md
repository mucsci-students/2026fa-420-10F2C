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
- "Change the capacity of Roddy 140 to 40", "Give Hogg a maximum of 9 credits", "Disable class pattern 4", "Turn off the pack_rooms setting"
- "Delete room Roddy 136" (see **Deleting** below)

**Setup.** Set `OPENAI_API_KEY` in your environment, or copy [`config/openai_api_key.example.txt`](config/openai_api_key.example.txt) to `config/openai_api_key.txt` and replace its contents with your OpenAI key. The local key file is ignored by Git; do not commit or share it. The environment variable takes precedence if both are set. The key is never shown on a page or written to a log. The model is `gpt-6-luna` unless `OPENAI_MODEL` is set:

```bash
export OPENAI_MODEL="gpt-6-luna"           # optional; this is the default
uv run python manage.py runserver
```

With no key set in either place, the assistant says so and nothing else changes.

**Changing and deleting.** The update tools (`update_room`, `update_lab`, `update_course`, `update_faculty`, `update_time_slot`, `update_timing_options`, `update_class_pattern`, `update_meeting`, `update_global_settings`, plus `add_meeting`) take only the values you want changed and merge them into the current record, then call the same controller the Edit pages use. A change that the scheduler library rejects is rejected as a whole, so nothing is half-applied; a request that changes nothing says so and does not mark the configuration as unsaved. Every real change is on the **History** page and can be undone there.

**Deleting** takes two messages. A `delete_*` tool only describes what would be deleted (the same dependency review the Delete pages show, including other items that go with it). The delete happens only when you confirm in a *new* message (`confirm_delete`); `cancel_delete` forgets it. A pending delete expires after 10 minutes, is refused if the configuration changed after it was described, and only the browser session that asked can confirm it. The assistant cannot confirm in the same message that describes the delete.

**Generating schedules.** Ask in your own words ("generate 5 schedules", "make some schedules with pack rooms on"). It also takes two messages, and uses the same scheduler as the Schedule Generator page:
1. `prepare_schedule_generation` checks that a configuration is open, validates it, and shows the generation limit and optimizer flags this run would use. You can change either in the chat ("make it 10", "turn off pack rooms"); the settings are shown again. They apply to **this run only**; the saved configuration is never modified by generating (use `update_global_settings` to change the saved ones).
2. In a *new* message, "go ahead" (`confirm_schedule_generation`) validates again and starts the run. It is refused if the settings were shown more than 10 minutes ago, the configuration changed since, or a delete is waiting. `cancel_schedule_generation` forgets the settings, or asks a running generation to stop.

While it works, the chat shows a progress line ("Generating schedules… found 3 of 10"). When it finishes the assistant says how many schedules were generated and, on the Schedule Viewer, the page reloads by itself to show them; on other pages the reply links to the viewer. If no feasible schedule exists, or the run fails, the reply explains why and nothing is added to the viewer (a failed run keeps earlier schedules; "no feasible schedule" clears them, as on the generator page). A run that takes longer than `AI_GENERATION_WAIT_SECONDS` (default 600, at most 3600) is left running; ask "how is the generation going?" (`check_generation_status`).

With no configuration open, the assistant says one must be created or loaded and offers both: `create_new_configuration` (then configure it in the chat, `validate_configuration`, and generate) or `load_saved_configuration` (saved configurations in this session; after loading and validating it carries on into the settings review), plus a **Load Configuration** link to the Configuration Editor's form for a JSON file on your computer. `load_saved_configuration` refuses when it would discard unsaved changes or loaded schedules. Quick replies ("Go ahead and generate", "Cancel", ...) appear as buttons under such messages and just send that text as an ordinary message.

**Saving.** "Save my configuration", "Download my config" or "Save as fall.json" (`save_configuration`) shows a file name box and a **Save JSON** button under the reply. The button posts to the Configuration Editor's own Save view (the Editor's Save form has the same optional file name box), so there is one export: the same validation and JSON, delivered as a normal browser download. Your browser decides where the file goes and what happens if a file with that name already exists; the app writes nothing to disk, so it can never overwrite a file. It cannot tell whether the download finished, so the assistant only says a download was requested, never that the file was saved. With no configuration open it explains there is nothing to save and offers Load and New; ask again afterwards.

**Starting a new configuration** (`create_new_configuration`) happens at once only when there are no unsaved changes and no generated schedules. Otherwise the assistant warns about what would be discarded and shows **Save JSON**, **Discard and Continue** and **Cancel**. Nothing changes until you choose; Cancel (or a stale or reused warning) leaves the configuration, its changes and its schedules as they were, and after Discard and Continue the old configuration can be brought back with Restore previous configuration in the Configuration Editor.

**Understanding you.** You can talk to the assistant the way you would to a person.
- *Part of a name is enough.* "Delete room 136" finds Roddy 136, "hog" finds Hogg, "cmsc 140" finds CMSC 140.01. When two items fit ("roddy"), it asks which you mean instead of guessing, and a near miss gets a "Did you mean ...?" with the real names.
- *Undo and redo.* `undo_changes` takes back the newest change, the newest N, or a specific one by its words ("put the room we deleted back" undoes that delete, with everything that was removed with it, and any later changes, and says so). `redo_changes` brings changes back and `show_change_history` lists them. It is the same history as the Undo/Redo buttons and the History page, so the same 25 changes apply. Every real change offers an **Undo the last change** quick reply.
- *Why generation found nothing.* When a run finds no feasible schedule, the reply says what is probably wrong (faculty minimum credits larger than the courses add up to, courses with more credits than the faculty can teach, a course nobody can teach, a course too big for its rooms) and lists your newest changes with a quick reply to undo them. `diagnose_configuration` ("check my configuration for problems") gives the same check on demand. These are likely causes, not proof: the solver has the final word.
- *Several things in one message.* "Put the room back, then generate a single schedule" makes the assistant call every tool the message needs, in order. The two-step safeguards still apply: a delete is only described and generation only shows its settings, and you confirm in a new message.

**Chats.** The conversation is kept on the server for each browser, so it is still there after you change pages or reload (open the panel and it is drawn again; whether the panel is open is remembered for the tab). The button at the left of the panel header opens the **chat history**, a sidebar like the one in Claude: your chats newest first, grouped by day (Today, Yesterday, Previous 7 days, ...). Click a chat to open it, use **New chat** for a fresh one, and the bin that appears on a row deletes it (the row asks "Delete?" in place, no pop-up). The sidebar is open by default on a wide screen and remembered in the browser; on a phone it slides over the chat. Each chat has its own memory for the AI, and a new chat or a switch forgets anything that was waiting for a "yes" (a delete, generation settings). If a request is still running when the page changes, the panel shows it as working and draws the answer when it is done. The history is locked while a request runs. At most 20 chats of 200 lines are kept (the oldest chat is dropped). Chats live with the browser session like the configuration does, so restarting the server starts fresh.

**How a request runs.**
- The AI can only call the tools in `gui/ai/tools.py`, and every tool calls the same controller the normal pages use. Duplicate names, unknown rooms and bad values are rejected the same way the forms reject them, and a rejected change leaves the configuration as it was.
- Your request stays on screen with a **"Working on it…"** status. When the request finishes, the status is replaced by the result, and the chat box takes a new request. If the AI changed something, the top bar shows **Unsaved changes** and the page behind the chat **updates in place**, with no reload: a new room appears in the list, new schedules in the Schedule Viewer. The chat stays open, and your scroll position, open dropdowns and list filter are kept. The page is *not* swapped while you have typed something into one of its forms (that would throw it away) or while the Schedule Generator page is running a generation; then the reply offers a **Refresh page** button instead.
- While a request is running, Send and Enter are ignored, so a double click or a second Enter does nothing. The server also refuses a second request from the same browser until the first one is done, so a change can't be applied twice.
- **Look first, then act.** The AI can read the configuration (lists, details) and then decide, so "delete the room with the smallest number" or "give the biggest room 10 more seats" work in one message. Lookups are only for the AI; any add, update, delete or confirmation ends the request with the application's own message, so the AI can't re-word what really happened. A request is limited to 6 model steps.
- **Short memory.** The last 6 chat messages are sent along so "yes, that one" or "make it 40 instead" are understood (set `AI_HISTORY_MESSAGES` from 0 to 20; `0` sends each request on its own). They are only a hint: names and numbers always come from the tools, which read the configuration as it is right now, edits you just made by hand included. Deleting still needs a separate confirmation that the application enforces itself.
- The reply comes from what the application actually did. A change says **"applied but not yet saved to a file"**: it's in the open configuration and marked as unsaved changes, but it isn't written to disk until you save it.
- AI service errors are retried at most twice, with a 60-second timeout. After that you get a "couldn't finish" message, and nothing is changed.

Tests use a fake AI (`tests/test_ai_chat.py`, `tests/test_ai_tools.py`, `tests/test_ai_changes.py`, `tests/test_ai_generation.py`, `tests/test_ai_chats.py`, `tests/test_ai_smarter.py`) or a mocked OpenAI endpoint (`tests/test_ai_langchain.py`), so no key is needed and no API calls are made.

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
| **AI** | `gui/ai/` | `tools.py`: the fixed tool set (each tool has a Pydantic argument schema and calls a controller); `generation.py`: validate, review settings, generate, load/new configuration; `undo.py`: undo, redo, change history; `diagnose.py`: why a run found nothing; `chats.py`: the saved chats; `service.py`: one request (duplicate guard, reply built from tool results); `runner.py`: the LangChain agent; `prompt.py`: base prompt. `gui/views_ai.py` has the endpoint the chat button posts to and a read-only progress endpoint; the button itself is `templates/gui/components/chat_widget.html` with `static/gui/js/chat.js`. |
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

Run the same checks as CI from the repository root:

```bash
uv sync --locked
uv build
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest --cov --cov-report=xml
```

Coverage measures the Model package in `app/` and fails below 80%. The Codecov upload is performed by CI; no OpenAI secret is needed for routine tests. The tests live in `tests/`: `test_crud_*` and `test_schedule_*` cover the model and CLI layer, `test_gui_*` cover the controllers and pages through Django's test client.

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
