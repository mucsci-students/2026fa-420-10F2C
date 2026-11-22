# 2026fa-420-10F2C — Course Scheduler

A web application for building, validating and solving university course-scheduling configurations, with a web GUI organized into three modes: **Configuration Editor**, **Schedule Generator** and **Schedule Viewer**. It is built on the [`course-constraint-scheduler`](https://github.com/mucsci/scheduler) library, which uses the Z3 solver to find schedules that satisfy every hard constraint (faculty availability, room and lab capacity, course conflicts, meeting patterns).

Like part of a schedule but not all of it? **Lock** the sections you want to keep and generate again: the locked sections stay exactly where they are and everything else is rearranged around them (see [Locking sections](#locking-sections-selective-regeneration)). An **AI Assistant** chat does all of this, and more, in everyday language (see [AI Assistant](#ai-assistant)).

The Sprint 1 command-line shell is still included and shares the same model code (see [Command-line shell](#command-line-shell-sprint-1)).

**Contributors:** Calvin Becker, Alan Reider, Henry Malesker, Joseph Lucks, Samsong Tamang, James Liranzo, Agustin Espinoza-Ortiz

## Contents

- [Install and start](#install-and-start)
- [The three modes](#the-three-modes)
- [Representative workflow](#representative-workflow)
- [Configuration Editor](#configuration-editor)
- [Schedule Generator](#schedule-generator)
- [Schedule Viewer](#schedule-viewer)
- [Locking sections (selective regeneration)](#locking-sections-selective-regeneration)
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

Every page has the same navigation bar with links to **Home**, **Configuration Editor**, **Schedule Generator** and **Schedule Viewer**, a status indicator for the configuration (**none loaded**, **Unsaved changes**, or **no unsaved changes**), and a **Dark mode** toggle. The round chat button in the corner opens the [AI Assistant](#ai-assistant).

| Mode | What it is for |
|---|---|
| **Configuration Editor** | Create, load, edit, validate and save a scheduler configuration. Eight areas: Time Slots, Rooms, Labs, Courses, Faculty, Class Patterns, Meetings, Global Settings. |
| **Schedule Generator** | Pick a configuration, optionally override the limit or optimizer flags for one run, see which locked sections the run will keep, and generate schedules. |
| **Schedule Viewer** | Browse generated or loaded schedules, lock the sections you like and generate again, load schedules from a file, export them as JSON or CSV, and clear them. |

## Representative workflow

This walk-through touches all three modes, starting from a fresh browser session (the example configuration is already loaded).

1. **Configuration Editor → Rooms → Add room.** Enter `Roddy 150`, capacity `30`. The room appears in the list and the navigation bar now shows **Unsaved changes**.
2. **Configuration Editor → Rooms**, try to delete `Roddy 136`. Its **Delete** button is disabled, and the row lists the courses that still use the room. Remove the room from those courses first, or leave it.
3. **Configuration Editor → Global Settings.** Set the generation limit to `5`, tick `pack_rooms`, and click **Save settings**. The page confirms each change.
4. **Configuration Editor → Validate configuration.** "Configuration is valid" appears. Click **Save configuration**; the browser downloads the JSON file and the status returns to **no unsaved changes**.
5. **Schedule Generator.** Leave the one-run fields alone (or change them — they never alter the saved configuration) and click **Generate schedules**. The button shows a busy state, and on success you land in the Schedule Viewer.
6. **Schedule Viewer.** Step through the schedules with **Previous** / **Next**, and switch between the course, room and faculty views.
7. **Keep what you like.** Click the padlock on a block in the calendar (or **Lock** in the **Keep sections you like** card). A banner says "1 section locked." Click **Generate again**: the locked section comes back exactly as it was and everything else is rearranged. The **Locked sections** card on the Schedule Generator lists the same section.
8. **Schedule Viewer → Export → Export All Schedules (JSON).** The file downloads.
9. **Schedule Viewer → Clear schedules**, confirm. Then **Load schedules from a file** with the JSON from step 8: the same schedules come back without running the solver again. (Clearing schedules does not remove locks.)
10. **AI Assistant (optional, needs an OpenAI key).** Click the chat button and type "lock CMSC 140.01 and generate 5 new schedules". The assistant locks the section and shows the generation settings (with the locked section listed); reply "go ahead" to run it. See [AI Assistant](#ai-assistant).

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
4. **Locked sections.** The **Locked sections** card lists every section you locked: instructor, room or lab, and when. A run keeps each one exactly as it is (instructor, room, lab, days and times) and rearranges everything else, and a note beside **Generate schedules** says so. Remove one with **Unlock**, or all of them with **Unlock all** (it asks first). With nothing locked the card says so. Lock sections in the Schedule Viewer or with the AI Assistant; see [Locking sections](#locking-sections-selective-regeneration).

The result is always one of:

| Outcome | What you see |
|---|---|
| Success | "Generated N schedule(s)." and the Schedule Viewer opens with the new results. |
| No feasible schedule | A warning that no schedule satisfies every hard constraint. Previous results are cleared. |
| Invalid configuration | The library's reason the configuration can't be scheduled. Previous results are kept. |
| Invalid override | The bad field (a limit that isn't a positive whole number, an unknown flag) is marked on the form. Nothing runs. |
| Locks can't be kept | An error that names the sections: two locks clash (the same room, lab or instructor at overlapping times), a lock no longer fits the open configuration (its instructor, room, lab, section or meeting times are gone), or no schedule can keep every lock. Nothing is generated and the schedules already in the viewer are kept. Unlock the sections named and try again. |
| Cancelled | "Generation was cancelled." Nothing is saved; previous results are kept. |
| Unexpected error | "Schedule generation failed unexpectedly" with the reason. Previous results are kept. |

Large limits can take a long time to solve; try a small number first.

## Schedule Viewer

The viewer shows whatever schedules are currently available, whether generated or loaded from a file.

- **Navigation.** The page shows how many schedules are available and which one you are viewing. **Previous** and **Next** step through them (they are disabled at either end), and `?schedule=N` in the address links straight to one.
- **Views.** One schedule at a time as a weekly overview, in three views:
  - **Course** — each meeting labelled by course section.
  - **Room** — grouped by room and lab; lab meetings appear under the lab, other meetings under the room.
  - **Faculty** — grouped by faculty member.

  Every block says the same four things in every view, filtered or not: the view's own item in bold (course, room/lab or faculty member), the time, then the other two (a missing room or faculty member is written out, for example "No room assigned"). Every block uses the same four lines and the same type sizes, and each hour of the calendar is tall enough for a 50-minute class to show all of them; a line too long for its block is shortened with an ellipsis. Hover or focus a block for everything in full. The calendar uses the whole width of the window and the week fits it without sideways scrolling (only a window narrower than about 780 px scrolls).
- **Picker.** Next to the view buttons, a searchable drop-down narrows the calendar to the courses (Course view), rooms and labs (Room view) or faculty (Faculty view) you tick. Click it and start typing: the list filters as you type, and spaces and punctuation don't matter (`cmsc140` finds `CMSC 140.01`; `roddy 1` finds `Roddy 136`). Tick as many items as you like, use **Select shown** to tick everything the search currently shows, **Clear** to untick all, then **Apply** (or press Enter). Ticked items appear as chips under the toolbar; click a chip's × to drop just that one, or **Show all**. A course with several sections also has an "all sections" choice (for example `CMSC 140`). The days are the columns of the weekly grid and the time axis stays the same, so picking items never moves the hours. `?resource=` (repeat it for each item) in the address links straight to a choice, and Previous/Next keep it. Without JavaScript the picker is a plain multi-select list with a **Show** button.
- **Clock.** **24-hour** or **12-hour (AM/PM)** buttons change every time on the page (axis, blocks, hover details). The choice is remembered for your browser session; `?time=12h` or `?time=24h` in the address sets it. It only changes how times are shown, never the schedule or the exported files.
- **Color key.** A collapsible **Color key** under the calendar lists what each color stands for in the current view, and each item keeps its color when you pick items. Names are always written on the blocks too, so color is never the only cue.
- **Nothing to show.** If a schedule has no meetings (for example only online sections), or nothing you picked meets in it, the calendar is replaced by a "No meetings to show" message that names any sections without meeting times and, after a pick, links back to **Show all**.
- **Locks.** Every calendar block has a padlock, a **Keep sections you like** card under the calendar lists the sections shown, and a banner appears while anything is locked, with **Generate again**. See [Locking sections](#locking-sections-selective-regeneration).

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
- **PDF:** a print-friendly PDF of one schedule, by room or lab or by faculty member, is exported from the same card; see [Exporting a PDF](#exporting-a-pdf) below.

### Exporting a PDF

The **Print-friendly PDF** part of the **Export** card makes a PDF of the schedule you are viewing, for printing
or sharing. It works for generated and loaded schedules alike, and never reruns the solver.

1. Open the schedule you want with **Previous** and **Next**. The form says which one it will export
   ("Exports Schedule 2 of 5").
2. In **What to export**, choose one of:
   - **By room or lab**: **All rooms and labs**, or one room or lab ("Room: Roddy 136", "Lab: Linux"). A room and
     a lab that share a name are listed separately.
   - **By faculty**: **All faculty**, or one faculty member.

   The list starts on the orientation that matches the view (By faculty in Faculty view, otherwise By room or lab).
3. Click **Export PDF**. The file downloads as `schedule-<n>-<what>.pdf`, for example
   `schedule-2-all-rooms-and-labs.pdf`, `schedule-2-lab-linux.pdf` or `schedule-2-faculty-hogg.pdf`.

What is in the PDF:

| By room or lab | By faculty |
|---|---|
| One section per room and one per lab, headed "Room: …" or "Lab: …", in name order | One section per faculty member, in name order |
| Columns: course, section, faculty, days, time | Columns: course, section, room or lab (with "room" or "lab"), days, time |
| A last section, **No room assigned**, for meetings with no room or lab (for example online sections) | A last section, **No faculty assigned**, for sections with no faculty member |

- Meetings in the same place at the same time on several days are one row ("Mon, Wed, Fri"). A section with no
  meeting times is still listed, as "No meeting times". A meeting with no room says "No room assigned"; it is never
  given a room.
- Every page names the schedule and the grouping ("Schedule 2 of 5 — By faculty"), what the export covers, and the
  page number. A section that continues onto another page repeats its heading and column headings there.
- Times use the viewer's clock choice (**24-hour** or **12-hour**), the same way throughout the document.
- A schedule with no course sections gives a one-page PDF that says so.
- **Paper:** US Letter (8.5 × 11 in), portrait, 0.75 in margins. Black text with gray rules and light gray heading
  bands, so it reads the same printed in grayscale.
- **Overwrite protection:** like the JSON and CSV exports, the PDF is a browser download, so the browser chooses
  where it goes and asks before replacing an existing file. The app never writes the PDF to disk itself.
- **Problems** (no schedules, a schedule that no longer exists, a choice that is not in the schedule, or the PDF
  failing to draw) bring you back to the viewer, on the same schedule, with a message. Nothing in the schedules or the
  configuration changes, whether the export works or not.

**Samples:** [by room or lab](docs/samples/schedule-by-room-or-lab.pdf) and
[by faculty](docs/samples/schedule-by-faculty.pdf), three pages each, made from invented demonstration data (no real
people, rooms or courses). Recreate them with:

```bash
uv run python scripts/make_sample_pdfs.py
```

The script uses the application's own code (`build_export`, then `render_pdf`), and its data is chosen to exercise
the layout: tables that continue onto the next page, a very long faculty name and room name, a lab meeting, an online
section with no room or meeting times, and a section with no faculty member. `tests/test_sample_pdfs.py` checks that
the script still runs and writes readable multi-page PDFs that list every section.

**Manual check (Sprint 4 §7).** Pagination and visual layout were checked by eye in both samples:

| Checked | By room or lab | By faculty |
|---|---|---|
| US Letter, portrait, even margins, page numbers 1–3 | ✓ | ✓ |
| Title and running header name the schedule and the grouping on every page | ✓ | ✓ |
| A table continued on the next page repeats its section and column headings | ✓ "Science Hall 204", page 1 → 2 | ✓ "Chen" 1 → 2, "Evans" 2 → 3 |
| Long names wrap inside their cell; nothing is cut off or overlaps | ✓ | ✓ |
| Rooms and labs labelled; no room, no faculty and no meeting times labelled | ✓ | ✓ |
| Readable with no color (grayscale) | ✓ | ✓ |
| Every section in the data appears | ✓ (also tested) | ✓ (also tested) |

**Limitations**

- One schedule per PDF; exporting the whole set of alternative schedules into one PDF is not supported.
- The PDF is a table per room, lab or faculty member, not a picture of the weekly calendar.
- A single word too long for its column (an unusually long name with no spaces) is split where the line runs out,
  without a hyphen. No text is lost.
- The running header at the top of each page is one line; a very long name there is shortened with an ellipsis. The
  full name is always in the title and the section heading.
- Only US Letter is supported.

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

## Locking sections (selective regeneration)

A **lock** keeps one section of a schedule exactly as it is: the same instructor, room, lab, days and times. The next time you generate schedules, every locked section stays where it is and the solver rearranges everything else around it. Use it when a schedule is mostly right: lock the parts you like and generate again, instead of starting over.

### Where to lock and unlock

Every place below reads and writes the **same list of locks**, so they always agree with each other.

- **Schedule Viewer, on the calendar.** Every block has a padlock. An open padlock means the section is free; click it to lock the section as this schedule places it. A closed padlock means it is locked in place; click it to unlock. A padlock whose tooltip says "Locked to a different placement" means the section is locked, but from a schedule that placed it somewhere else; click it to lock the section as shown here instead.
- **Schedule Viewer, "Keep sections you like" card.** Lists every section the calendar is showing, grouped by instructor, with room or lab, times, and **Lock** / **Unlock** for each. An instructor with several sections also has **Lock all N** and **Unlock all N**.
- **Schedule Viewer, banner.** While anything is locked, a banner says how many sections are locked and offers **Generate again** (with a box for how many schedules, filled in with the saved limit; it applies to this run only), **Generation options** and **Unlock all** (which asks first). With JavaScript the run starts in the background and the banner turns into a progress bar with a **Cancel generation** button; the page then reloads on schedule 1 of the new results. Without JavaScript the button posts to the Schedule Generator, which runs the same generation.
- **Schedule Generator, "Locked sections" card.** Lists the locked sections (section, instructor, room or lab, when) with **Unlock** for each and **Unlock all**.
- **AI Assistant.** "Lock CMSC 141.01", "Which sections are locked?", "Unlock everything". See [AI Assistant](#ai-assistant).

After a lock or unlock you are sent back to the page you were on, with the same schedule, view and picks. The confirmation is an information message, not a green success one, because locking does not change the configuration and so has no Undo.

### What a lock remembers

The section's whole placement (instructor, room, lab and meetings) as it was in the schedule you locked it from; the lists say "locked from schedule 2". The lock holds its own copy, so it survives generating, loading or clearing schedules. Locking a section again from another schedule replaces the earlier lock. Locking a section that is already locked exactly like this changes nothing.

### Rules

- **Clashing locks are refused when you click.** Two sections locked into the same room, the same lab, or taught by the same instructor at overlapping times cannot both be kept, so the second lock is refused with a message naming both sections. Nothing is locked.
- **The solver keeps them.** The scheduler library has no lock feature, so a lock becomes four extra hard rules for that section (the instructor, the room, the lab or "no lab", and the meeting times), added just before the solver runs. Every schedule it returns therefore keeps the locks; nothing is generated and thrown away. As a final safety net each result is checked again, and a schedule that does not keep a lock is never stored.
- **A lock that cannot be kept stops the run.** If its instructor, room, lab, section or meeting times are no longer in the open configuration (for example after you loaded a different one), or no schedule can satisfy every lock, nothing is generated, the message names the sections, and the schedules already in the viewer are kept. This is different from plain "no feasible schedule", which clears them.
- **Locks are not part of the configuration.** Locking and unlocking never change the configuration, never mark it as having unsaved changes, are not in the undo history and are not in a saved configuration file or an exported schedule. They live in the browser session, so restarting the server clears them.
- **What clears locks.** **New configuration** and **Restore previous configuration** clear them. Loading a configuration or switching to a saved one keeps them, and they are checked when you generate (see above). Clearing schedules and generating new schedules leave them in place.
- **Out of date locks.** A lock keeps the placement it was made with, even if you later edit the configuration. If the edit made it impossible, the next run says so and names the section.

### How it is built (MVC)

| Layer | Where |
|---|---|
| **Model** | `app/locks.py`: `Lock` (one locked placement), `LockSet` (the session's locks, with a `version` that goes up on every real change) and `find_conflicts` (clashes between locks, without the solver). `app/lock_solver.py`: turns locks into Z3 rules (`plan_locks`, `apply_plan`) and double-checks results (`unkept_locks`). It is the **only** module that reaches into the library's private solver parts, so a library update that changes them breaks one file, and `tests/test_locks_real_solver.py` fails to say so. `app/schedule_ops.py` and `app/generation_job.py` pass the locks to the run. `app/session.py` holds `Session.locks`. |
| **Controller** | `gui/controllers/locks.py`: lock, unlock, lock or unlock one instructor's sections, clear all, and the all-or-nothing `lock_sections` / `unlock_sections` the assistant uses. Every refusal is a `ControllerError` with a plain sentence. |
| **View** | `gui/views_locks.py` (POST-only; the "next" address is only trusted when it points at this site), the lock panels in `gui/views.py`, and the templates `components/lock_form.html` (the one hidden form behind every lock button), `lock_banner.html`, `lock_sections.html`, `lock_panel.html`, `regenerate_form.html` and `locks_clear.html`, with `static/gui/js/generation_progress.js`. |
| **AI** | `gui/ai/locks.py` (see [AI Assistant](#ai-assistant)). |

Tests: `tests/test_locks.py`, `test_lock_controller.py`, `test_lock_views.py`, `test_lock_solver.py`, `test_lock_regenerate.py`, `test_locks_real_solver.py` (runs the real solver), `test_schedule_ops_locks.py`, `test_session_locks.py`, `test_generation_locks.py` and, for the chat, `test_ai_locks.py`.

## AI Assistant

Click the round chat button in the bottom-right corner of any page and type a request in everyday language. Hover the button and click the small arrow to slide it out of the way; a small tab at the screen edge brings it back. For example:

- "What can you do?"
- "List all rooms", "How many credits is CMSC 420?", "Show me faculty Hogg"
- "Add a room named RODDY150 with capacity 35"
- "Add course CMSC 421 with 3 credits, taught by Hogg in RODDY150"
- "Add a time slot on Friday from 17:00 to 19:00", "Add a class pattern for 3 credits meeting Monday for 150 minutes"
- "Change the capacity of Roddy 140 to 40", "Give Hogg a maximum of 9 credits", "Disable class pattern 4", "Turn off the pack_rooms setting"
- "Delete room Roddy 136" (see **Deleting** below)
- "Lock CMSC 141.01", "Which sections are locked?", "Unlock everything", "Lock CMSC 152.01 and generate 5 new schedules" (see **Locking sections** below)

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

**Locking sections.** "Lock CMSC 141.01", "lock everything Hogg teaches", "lock the Monday classes in Roddy 136", "unlock CMSC 141.01", "unlock everything" and "which sections are locked?" all work. The tools are `lock_sections`, `unlock_sections`, `view_locked_sections`, `unlock_all_sections`, `lock_faculty_sections` and `unlock_faculty_sections`, plus `list_schedule_sections`, a lookup only the assistant reads, so it can find the exact sections you described before acting. They are in `gui/ai/locks.py` and call `gui/controllers/locks.py`, like the padlock buttons do. See [Locking sections](#locking-sections-selective-regeneration) for what a lock is.
- **The same locks everywhere.** The chat, the padlocks and cards in the Schedule Viewer and the **Locked sections** card on the Schedule Generator read and write one list. A lock made in the chat appears on the page behind it at once (the page updates in place), and the chat lists exactly the sections the Generator lists: instructor, room or lab, days and times (in the clock the Schedule Viewer uses), and the schedule each was locked from.
- **Not part of the configuration.** Locking and unlocking never change the configuration, never mark it as unsaved and are not in the undo history, so these replies never say "not yet saved to a file". Every reply says "The configuration was not changed."
- **Which schedule.** The one open in the Schedule Viewer (the chat sends the page's schedule number). On any other page it uses schedule 1 and the reply says so; "lock it from schedule 3" picks one explicitly.
- **Invalid requests change nothing.** A section that is not in that schedule gets "I couldn't find a section called ... in schedule N", with "Did you mean ...?" when something looks close. The same goes for an instructor who teaches nothing in it, a section that is not locked (when unlocking), a schedule number that does not exist, and no schedules at all. No lock is created or changed and the configuration is untouched.
- **All or nothing.** One message can lock or unlock several sections in one call. If any name is unknown or ambiguous, or the locks would clash (the same room, lab or instructor at overlapping times), nothing changes. A name that fits two sections ("CMSC 141" when there is a .01 and a .02) is asked about, never guessed.
- **At once.** Unlike deleting, locks take one message with no confirmation (they are cheap to undo), and they do not interrupt or drop a request that is waiting for details.
- **Smarter requests.** `list_schedule_sections` lets the assistant read the schedule first ("lock the Monday classes in Roddy 136", "lock all of CMSC 141"). `lock_faculty_sections` and `unlock_faculty_sections` handle one instructor's sections, `unlock_all_sections` clears every lock, and `lock_sections` with `replace_existing_locks` makes the named sections the only locks ("lock only CMSC 141.01"). Several lock requests in one message are carried out in order ("unlock CMSC 141.01 and lock everything Barr teaches").
- **Lock and generate in one message.** "Lock CMSC 152.01 and generate 5 new schedules" locks the section and then shows the generation settings, with the locked section listed and the limit you asked for. As everywhere, generating takes a second message: reply "go ahead". The assistant is told to make both calls in one go. Because a lock's reply is the application's own final answer, a safety net on the server (`finish_generation_request` in `gui/ai/locks.py`) shows the generation settings itself when the assistant locked or unlocked successfully, you clearly asked to generate, and the assistant did not call a generation tool. It stays out when you postpone or refuse ("lock it, I'll generate later", "don't generate yet") and when a lock fails.
- **No locks.** Asking which sections are locked, with none locked, says "No sections are currently locked."

**Saving.** "Save my configuration", "Download my config" or "Save as fall.json" (`save_configuration`) shows a file name box and a **Save JSON** button under the reply. The button posts to the Configuration Editor's own Save view (the Editor's Save form has the same optional file name box), so there is one export: the same validation and JSON, delivered as a normal browser download. Your browser decides where the file goes and what happens if a file with that name already exists; the app writes nothing to disk, so it can never overwrite a file. It cannot tell whether the download finished, so the assistant only says a download was requested, never that the file was saved. With no configuration open it explains there is nothing to save and offers Load and New; ask again afterwards.

**Exporting a PDF.** "Export the schedule as a PDF by room", "Print the faculty schedules", "PDF for Hogg" or "PDF of
lab Roddy 147 from schedule 2" (`export_schedule_pdf`, in `gui/ai/exports.py`) shows an **Export PDF** button under
the reply. The button is the Schedule Viewer's own PDF export (see [Exporting a PDF](#exporting-a-pdf)), so the PDF,
its file name and its checks are exactly the same, and it is a normal browser download: the assistant only says it is
ready, never that it was saved. It exports the schedule you name, otherwise the one open in the Schedule Viewer,
otherwise schedule 1 (and says so). A room, lab or faculty member is found the way every other request finds a name
("room 136", "hogg"); a name that is both a room and a lab is asked about, with a button for each. An unknown name,
a schedule number that does not exist, or no schedules at all gets a clear reply and no button. Asking never changes
the schedules or the configuration.

**Starting a new configuration** (`create_new_configuration`) happens at once only when there are no unsaved changes and no generated schedules. Otherwise the assistant warns about what would be discarded and shows **Save JSON**, **Discard and Continue** and **Cancel**. Nothing changes until you choose; Cancel (or a stale or reused warning) leaves the configuration, its changes and its schedules as they were, and after Discard and Continue the old configuration can be brought back with Restore previous configuration in the Configuration Editor.

**Understanding you.** You can talk to the assistant the way you would to a person.
- *Part of a name is enough.* "Delete room 136" finds Roddy 136, "hog" finds Hogg, "cmsc 140" finds CMSC 140.01. When two items fit ("roddy"), it asks which you mean instead of guessing, and a near miss gets a "Did you mean ...?" with the real names.
- *Undo and redo.* `undo_changes` takes back the newest change, the newest N, or a specific one by its words ("put the room we deleted back" undoes that delete, with everything that was removed with it, and any later changes, and says so). `redo_changes` brings changes back and `show_change_history` lists them. It is the same history as the Undo/Redo buttons and the History page, so the same 25 changes apply. Every real change offers an **Undo the last change** quick reply.
- *Why generation found nothing.* When a run finds no feasible schedule, the reply says what is probably wrong (faculty minimum credits larger than the courses add up to, courses with more credits than the faculty can teach, a course nobody can teach, a course too big for its rooms) and lists your newest changes with a quick reply to undo them. `diagnose_configuration` ("check my configuration for problems") gives the same check on demand. These are likely causes, not proof: the solver has the final word.
- *Several things in one message.* "Put the room back, then generate a single schedule" makes the assistant call every tool the message needs, in order. The two-step safeguards still apply: a delete is only described and generation only shows its settings, and you confirm in a new message. Locking works the same way: "lock CMSC 141.01 and generate 5 schedules" locks, then shows the generation settings with the locked section listed.
- *Asking for what is missing.* A request that lacks a value ("Add a room named RODDY150" has no capacity) or names something that fits several items is not run. The assistant asks for everything that is missing in one message, and nothing changes while it waits. Answer in your own words ("it holds 35") and it finishes the original request through the same checks; a value you give again corrects the earlier one, and you can say "never mind" (`cancel_pending_request`) to drop it. A request waits for ten minutes and is forgotten when another chat opens or a different configuration replaces the open one. While it waits, tools that change the configuration are refused until it is finished or cancelled; reading, and locking, still work.

**Chats.** The conversation is kept on the server for each browser, so it is still there after you change pages or reload (open the panel and it is drawn again; whether the panel is open is remembered for the tab). The button at the left of the panel header opens the **chat history**, a sidebar like the one in Claude: your chats newest first, grouped by day (Today, Yesterday, Previous 7 days, ...). Click a chat to open it, use **New chat** for a fresh one, and the bin that appears on a row deletes it (the row asks "Delete?" in place, no pop-up). The sidebar is open by default on a wide screen and remembered in the browser; on a phone it slides over the chat. Each chat has its own memory for the AI, and a new chat or a switch forgets anything that was waiting for a "yes" (a delete, generation settings). If a request is still running when the page changes, the panel shows it as working and draws the answer when it is done. The history is locked while a request runs. At most 20 chats of 200 lines are kept (the oldest chat is dropped). Chats live with the browser session like the configuration does, so restarting the server starts fresh.

**How a request runs.**
- The AI can only call the tools in `gui/ai/tools.py`, and every tool calls the same controller the normal pages use. Duplicate names, unknown rooms and bad values are rejected the same way the forms reject them, and a rejected change leaves the configuration as it was.
- Your request stays on screen with a **"Working on it…"** status. When the request finishes, the status is replaced by the result, and the chat box takes a new request. If the AI changed something, the top bar shows **Unsaved changes** and the page behind the chat **updates in place**, with no reload: a new room appears in the list, new schedules in the Schedule Viewer. The chat stays open, and your scroll position, open dropdowns and list filter are kept. The page is *not* swapped while you have typed something into one of its forms (that would throw it away) or while the Schedule Generator page is running a generation; then the reply offers a **Refresh page** button instead.
- While a request is running, Send and Enter are ignored, so a double click or a second Enter does nothing. The server also refuses a second request from the same browser until the first one is done, so a change can't be applied twice.
- **Look first, then act.** The AI can read the configuration (lists, details) and then decide, so "delete the room with the smallest number" or "give the biggest room 10 more seats" work in one message. Lookups are only for the AI; any add, update, delete or confirmation ends the request with the application's own message, so the AI can't re-word what really happened. A request is limited to 6 model steps.
- **Short memory.** The last 6 chat messages are sent along so "yes, that one" or "make it 40 instead" are understood (set `AI_HISTORY_MESSAGES` from 0 to 20; `0` sends each request on its own). They are only a hint: names and numbers always come from the tools, which read the configuration as it is right now, edits you just made by hand included. Deleting still needs a separate confirmation that the application enforces itself.
- **Only real actions are reported.** The AI's own text never counts as an action: if it says something was added, changed or deleted but no action tool ran, that text is replaced with "That wasn't done: no action ran, so nothing was changed." Every add, change or delete is also checked against the configuration itself, so a step that reports success but left the configuration unchanged is reported as a failure, and a change that did happen is always reported.
- The reply comes from what the application actually did. A change says **"applied but not yet saved to a file"**: it's in the open configuration and marked as unsaved changes, but it isn't written to disk until you save it.
- AI service errors are retried at most twice, with a 60-second timeout. After that you get a "couldn't finish" message, and nothing is changed.

Tests use a fake AI (`tests/test_ai_chat.py`, `tests/test_ai_tools.py`, `tests/test_ai_changes.py`, `tests/test_ai_generation.py`, `tests/test_ai_chats.py`, `tests/test_ai_smarter.py`, `tests/test_ai_locks.py`, `tests/test_ai_pdf_export.py`) or a mocked OpenAI endpoint (`tests/test_ai_langchain.py`), so no key is needed and no API calls are made.

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
| | `app/generation_job.py` | One generation run on a background thread. `GenerationJob` is the subject of the Observer pattern: it notifies `GenerationObserver`s (`ProgressTracker` here, `ResultsStore` in the controller) of progress and of the result (see [Design patterns](#design-patterns)). |
| | `app/schedule_io.py` | Neutral schedule records (`Assignment`, `MeetingTime`) used by both generated and loaded schedules; JSON/CSV reading, writing and validation. |
| | `app/schedule_view.py` | One schedule as typed `MeetingBlock`s (course and section split apart, the room or lab kept with its kind), and the `Grouping` strategies that read it by course, by room or lab, or by faculty member (see [Design patterns](#design-patterns)). |
| | `app/schedule_export.py` | One schedule arranged into sections for a printed export, by room or lab or by faculty member: `build_export` returns a `ScheduleExport` of `ExportSection`s and `ExportRow`s, built from schedule records alone so imported schedules work. It holds the content only and has no PDF code: `gui/schedule_pdf.py` draws it, and the Schedule Viewer's **Export PDF** uses it (see [Exporting a PDF](#exporting-a-pdf)). |
| | `app/locks.py`, `app/lock_solver.py` | Section locks (selective regeneration): `LockSet` holds the session's locks and spots clashes between them; `lock_solver` turns locks into extra solver rules and double-checks results. See [Locking sections](#locking-sections-selective-regeneration). |
| | `course-constraint-scheduler` | The configuration models, validation rules and Z3 solver. Validation is never reimplemented in this project. |
| **Controller** | `gui/controllers/` | One module per area: `config_controller.py` (lifecycle), `timeslots.py`, `rooms.py`, `labs.py`, `courses.py`, `faculty.py`, `patterns.py`, `meetings.py`, `settings.py`, `schedule_controller.py` (generate, load, export, clear), `locks.py` (lock and unlock sections), `history_controller.py` (undo, redo), `dependencies.py` (what each record is used by, shared by every delete) and `pdf_export.py` (the PDF export: what can be exported, and building one). `errors.py` defines `ControllerError` / `FieldError`; `uploads.py` reads uploaded files safely. Controllers return plain data and never touch templates or `HttpResponse`. |
| **View** | `gui/views.py`, `gui/views_*.py` | Thin request handlers: call a controller, then redirect with a message or re-render the form with its errors. `views.py` has the home page, the configuration lifecycle, the generator form and the viewer page; each configuration area has its own `views_<area>.py` (`views_timeslots.py`, `views_rooms.py`, ...). `views_errors.py` renders the error pages. `views_locks.py` (lock, unlock, unlock all), `views_generation.py` (the progress bar's start, status and cancel endpoints), `views_delete.py` and `views_rename.py` (the review-and-confirm pages), `views_history.py` (undo, redo, history) and `views_ai.py` (the chat) follow the same pattern. |
| | `gui/calendar_layout.py` | The Schedule Viewer's weekly calendar as presentation data (`ScheduleGrid`): where each block sits, how overlapping blocks share a day column, colors, and how times are written. No request handling and no Django imports. |
| | `gui/schedule_pdf.py` | A schedule export as a print-friendly PDF: `render_pdf(export, schedule_label, time_format)` returns the bytes. US Letter, portrait, grayscale-safe, headings repeated on continuation pages. Presentation only; it writes no files and has no Django imports. Uses ReportLab. |
| | `gui/templates/gui/` | Pages and shared components (`components/`), including `base.html` (navigation, status, loading banner). |
| | `gui/forms.py` | Django forms: field types, labels, help text, confirmation checkboxes. |
| | `gui/static/gui/` | CSS and JavaScript (`loading.js` for busy states, `theme.js` for dark mode, `generation_progress.js` for the live progress bar, `schedule_viewer.js` for the calendar and picker, `history.js` for the undo and redo shortcuts, `chat.js` for the assistant). |
| **AI** | `gui/ai/` | `tools.py`: the fixed tool set (each tool has a Pydantic argument schema and calls a controller); `generation.py`: validate, review settings, generate, load/new configuration; `undo.py`: undo, redo, change history; `locks.py`: lock, unlock and list sections, and the safety net for "lock and generate" requests; `changes.py`: the update and delete tools; `lifecycle.py`: save, new and load configuration; `clarify.py`: asking for missing details; `pending.py`: the Command pattern behind describe-then-confirm steps (a delete, a generation review); `base.py`: what every tool shares; `diagnose.py`: why a run found nothing; `chats.py`: the saved chats; `service.py`: one request (duplicate guard, reply built from tool results); `runner.py`: the LangChain agent; `prompt.py`: base prompt. `gui/views_ai.py` has the endpoint the chat button posts to and a read-only progress endpoint; the button itself is `templates/gui/components/chat_widget.html` with `static/gui/js/chat.js`. |
| **Glue** | `gui/session_store.py` | Gives each browser its own `Session` (keyed by an id in a signed-cookie session). |
| | `gui/middleware.py` | Turns unexpected exceptions into the friendly error page and logs the traceback. |
| | `config/` | Django settings and root URL configuration; `gui/urls.py` maps each URL to a view. |

The Sprint 1 shell (`app/shell.py`, `app/commands/`) uses the same Model layer, which is why both interfaces validate and save configurations identically.

### Design patterns

MVC (above) is one of the patterns used. The others are described here as they are added: Memento, Observer and Adapter (carried forward from Sprint 3) and, new in Sprint 4, Strategy, Template Method and Command. That is seven with MVC.

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

#### Observer (schedule generation)

- **Problem.** When a background generation run makes progress or ends, more than one part of the application needs to
  know: the session must store (or clear) the schedules and be released, and the progress display needs the number of
  schedules found so far. A job that was handed one callback could serve only one of them, and adding another would
  mean changing the job.
- **Where.** `app/generation_job.py` (the pattern: `GenerationJob`, `GenerationObserver`, `ProgressTracker`),
  `gui/controllers/schedule_controller.py` (`ResultsStore`, and `start_generation`, where it is subscribed). Tests:
  `tests/test_generation_observers.py` and `tests/test_generation_progress.py`.
- **Participants.**
  - *Subject*: `GenerationJob` keeps a list of observers (`subscribe`, `unsubscribe`, `observers`) and notifies each
    one, in subscription order, from its worker thread. It only runs the solver and notifies; it does not store
    anything or track progress itself.
  - *Observer*: the base class `GenerationObserver` with two no-op hooks, `on_progress(job, found, limit)` after each
    schedule the solver finds and `on_finished(job, result)` once when the run ends. An observer overrides only the
    hooks it needs.
  - *Concrete observers*: `ProgressTracker` (found, limit and percent; every job subscribes one first, and
    `job.snapshot()`, which the progress bar and the AI chat poll, reads it) and `ResultsStore` (on a successful run it
    stores the schedules, when no schedule is feasible it clears the old ones, for a cancel, an invalid configuration
    or an error it keeps them, and it always releases the session).
- **How they interact.** `start_generation` creates the job, subscribes a `ResultsStore` (the tracker is already
  subscribed) and starts it. For each schedule the solver finds, the job tells every observer, the tracker first, so
  it is up to date before anyone else hears about it. When the run ends the job tells every observer the result,
  **before** the job counts as finished, so anyone who sees "finished" can rely on the results having been stored.
- **When an observer fails.** Every observer is always notified. A failing `on_progress` is logged and ignored. A
  failing `on_finished` (for example, storing the results failed) makes the job's result a runtime error with that
  message, and the other observers still receive the original result. The old `on_finish=` argument still works: it
  subscribes a small observer that calls the function.
- **Why it fits.** The subject does not know who is listening, so a new subscriber (a log line, a test recorder, another
  display) needs no change to the job (open/closed); each observer has one job (single responsibility); and the job
  depends on the abstract `GenerationObserver`, not on the controller or the session, which keeps the model layer free
  of Django and of the GUI.
#### Adapter (the AI service)

- **Problem.** The chat needs a language model to pick tools, but the rest of the app should not depend on LangChain or
  OpenAI. Their tool objects, agent loop and message format are not ours, and routine tests must run with no AI and no
  API key.
- **Where.** `gui/ai/runner.py` (`Runner`, `LangChainRunner`), used by `gui/ai/service.py` (`get_runner`, `_run`). The
  tools it adapts are `AiTool` and `ToolBox` (`gui/ai/base.py`, `gui/ai/tools.py`). Tests: `tests/test_ai_adapter.py`,
  `tests/test_ai_langchain.py`.
- **Participants.**
  - *Target*: `Runner`, the one interface the app wants: `run(text, toolbox)` returns the model's own text, or an empty
    string when an action's own result is the answer.
  - *Client*: `service._run` in `gui/ai/service.py`. It asks `get_runner()` for a runner and calls `run`; it knows
    nothing about LangChain.
  - *Adaptee*: LangChain's agent and tool classes (`create_agent`, `StructuredTool`), talking to OpenAI.
  - *Adapter*: `LangChainRunner`. `langchain_tools()` turns each of our tools (name, description, argument schema,
    handler) into a LangChain tool, and `reply_from()` turns LangChain's answer back into plain text. Reading the API
    key (`load_api_key`) is kept separate from this translation.
- **How they interact.** The client calls `run`. The adapter builds the LangChain tools from the request's tool box and
  starts the agent. Every tool call the model makes is forwarded to `toolbox.call`, which checks the arguments, runs
  the controller and records what really happened. When the agent stops, `reply_from` returns the single piece of text
  the client expects.
- **Why it fits.** The client talks only to the interface it wants, and the incompatible LangChain interface is
  converted in one class. Replacing the real AI with a fake one (as the tests do) or with another provider only
  changes what `get_runner` returns.

#### Strategy (schedule groupings) — new in Sprint 4

- **Problem.** The same schedule is read three ways: by course, by room or lab, and by faculty member. Each way
  decides which item a meeting belongs to, what the block is called, which other facts go beside it, which choices
  the picker offers and which meetings a pick keeps. Before Sprint 4 those decisions were `if view_mode == ...`
  branches repeated across five helper functions and two lookup tables in `gui/views.py`, so a change to one way of
  grouping meant editing every one of them, and nothing outside the viewer could reuse the rules.
- **Where.** `app/schedule_view.py` (`Grouping`, `CourseGrouping`, `RoomLabGrouping`, `FacultyGrouping`, the
  `GROUPINGS` registry and `grouping_for`). Used by `gui/calendar_layout.py` (`schedule_grid`, `layout_week`),
  `gui/views.py` (`schedule_viewer`) and `app/schedule_export.py` (`build_export`). Tests:
  `tests/test_schedule_view.py`, `tests/test_schedule_export_data.py`.
- **Participants.**
  - *Strategy*: the abstract `Grouping`. Each concrete grouping supplies `group_key(course, faculty, resource)` (the
    item a meeting belongs to, with its kind), `details(block)` (the other two facts) and `options(assignments)` (the
    picker's choices), plus the words for its items (`noun`, `plural`, `unassigned_label`). `owner(block)`,
    `label(block)` and `select(blocks, chosen)` (the meetings a pick keeps) are written once on `Grouping` in terms
    of those.
  - *Concrete strategies*: `CourseGrouping` (picking a course name keeps all of its sections), `RoomLabGrouping` (a
    lab meeting belongs to the lab, any other meeting to the room) and `FacultyGrouping`. A meeting with no room or
    no faculty member is labelled "No room assigned" / "No faculty assigned" by the strategy that would have shown
    it; none of them invents one.
  - *Context*: `layout_week` in `gui/calendar_layout.py`. It is handed a `Grouping` and asks it for each block's
    label and details and for the colors' keys; it never checks which grouping it has.
  - *Client*: `schedule_viewer` in `gui/views.py` chooses the strategy from the `?view=` value
    (`GROUPINGS[view_mode]`) and uses the same object for the picker's choices and its wording.
  - *Second context*: `build_export` in `app/schedule_export.py`. It is given an orientation (`"rooms"` or
    `"faculty"`), takes that grouping, and asks it which section each meeting belongs to and what the section for
    unassigned meetings is called. The same two strategy objects therefore decide what the calendar shows and what
    an export contains, so the two cannot disagree about where a lab meeting goes or how a missing room is labelled.
- **How they interact.** The view reads `?view=`, looks the grouping up, and asks it for the picker options.
  `schedule_grid` turns the schedule into `MeetingBlock`s, has the grouping `select` the picked ones, and passes the
  blocks and the grouping to `layout_week`, which positions them and asks the grouping what each one says.
- **Why it fits.** The three groupings are interchangeable answers to the same questions, and the choice is made at
  run time from the address. With the rules behind one interface the calendar code has no view-mode branches, each
  grouping can be tested on its own without a request or a template, and another way of reading a schedule is a new
  class and one registry entry, not an edit to every helper (open/closed).

#### Template Method (schedule PDF documents) — new in Sprint 4

- **Problem.** A room/lab export and a faculty export are the same kind of document: a title naming the schedule
  and what is covered, one table per section with headings that repeat when it runs onto another page, a line
  saying so when there is nothing to export, and a header and page number on every page. They differ only in what
  the document is called, how a section is headed, and which columns its table has. Writing the two as separate
  functions would duplicate the page setup, table styling and pagination rules, and the two would drift apart.
- **Where.** `gui/schedule_pdf.py` (`ScheduleDocument`, `RoomLabDocument`, `FacultyDocument`, `DOCUMENTS`,
  `render_pdf`). Tests: `tests/test_schedule_pdf.py`.
- **Participants.**
  - *Abstract class*: `ScheduleDocument`. Its template method is `build()`, which always runs the same steps in the
    same order: `title_block()`, then `empty_block()` or one `section_block(section)` per section, then the page
    setup with `page_furniture()` on every page. Those steps are written once on the base class.
  - *Primitive operations*: `section_heading(section)` and `columns()`, both abstract, and the `name` attribute.
    `section_block` calls them to head and fill each table; `title` uses `name`.
  - *Concrete classes*: `RoomLabDocument` heads a section "Room: Roddy 136" or "Lab: Roddy 147" and shows a Faculty
    column; `FacultyDocument` heads it "Faculty: Hogg" and shows a Room or lab column, which reads "No room
    assigned" when a meeting has none. Neither overrides `build()` or any shared step.
- **How they interact.** `render_pdf` looks the class up by the export's orientation (`DOCUMENTS`), constructs it
  with the export, and calls `build()`. `build()` walks the export's sections and, for each one, asks the subclass
  for the heading and the columns. The subclass never controls the order of the steps or the page layout.
- **Why it fits.** The algorithm (the document's skeleton) is fixed and the variation is confined to a few steps,
  which is the case Template Method is for. It is a different job from Strategy above: the `Grouping` strategies
  decide which meetings go in which section; the document classes decide how a section is laid out on paper.

#### Command (pending actions) — new in Sprint 4

- **Problem.** Some assistant actions must never happen in the same message that asked for them. The assistant first
  *describes* what it would do (a delete and everything that goes with it, or the generation settings it would use),
  remembers it, and only does it when the user confirms in a *later* message. That "describe, wait, confirm or
  cancel" flow was written twice by hand, once for deletes and once for generation. Each copy had its own steps
  (is anything waiting? was it asked in this very message? has it expired? is it still what was described?) and kept
  its request in a raw string-keyed attribute on the session that was cleared by hand with `setattr(session, ..., None)`.
  A third kind of waiting thing would have meant a third copy.
- **Where.** `gui/ai/pending.py` (the pattern), `gui/ai/changes.py` (`PendingDelete`, `confirm_delete`,
  `cancel_delete`), `gui/ai/generation.py` (`PendingGeneration`, `confirm_schedule_generation`,
  `cancel_schedule_generation`). Tests: `tests/test_ai_pending.py`, and the existing `tests/test_ai_changes.py`,
  `tests/test_ai_generation.py`, `tests/test_ai_clarify.py`, `tests/test_ai_chats.py`.
- **Participants.**
  - *Command*: the abstract `PendingAction`. It holds what is needed to carry an action out later, and offers
    `execute(request)` plus what to say when it can no longer run (`same_request_message`, `expired_message`, and
    optionally `blocked_message` and `stale_message`).
  - *Concrete commands*: `PendingDelete` (a described delete: its label, the configuration version it described and
    the work to do) and `PendingGeneration` (the reviewed limit and optimizer flags, the configuration and the locked
    sections they were checked against).
  - *Receivers*: the objects that do the real work, which the commands only call: the delete controllers
    (`rooms.delete_room`, ...) for a delete, and `schedule_controller.start_generation` for a run.
  - *Invoker*: the shared steps in `pending.py`: `stage` (remember a command), `confirm` (the one confirmation flow),
    `take` (forget it and hand it back, for cancel) and `forget`. The `confirm_delete` and `confirm_schedule_generation`
    tools call `confirm`; `cancel_delete` and `cancel_schedule_generation` call `take`.
  - *Client*: the tools that describe the action (`delete_room`, ..., `prepare_schedule_generation`). They build the
    command and stage it; they never run it.
- **How they interact.** `delete_room` checks the delete, builds a `PendingDelete` and stages it in the session's
  slot, then answers with the description. Nothing has been deleted. In a later message the AI calls `confirm_delete`,
  which asks `pending.confirm` to run the same checks for every kind of command, in this order: something is
  waiting; it was not staged by this very message; nothing blocks it (a command can say so); it is used up whatever
  happens next; it has not expired; it is still what was described (the configuration, and for a run the locks, have
  not changed). Only then is `execute` called, which runs the receiver's work. Each failed check ends with the
  command's own sentence and nothing is changed. A generation review is the same with `PendingGeneration`; reviewing
  the settings also drops a waiting delete, so only one thing waits for a "yes" at a time.
- **Why it fits.** A request is turned into an object that is created now and run later, which is what Command is
  for (the lecture's "queue, schedule or undo individual actions"). The code that confirms an action does not know
  what the action is, and a new kind of waiting action is one new class, not another copy of the flow
  (open/closed). The checks that decide whether it may still run are written once, so a delete and a run can no
  longer drift apart. This is a different job from Memento above: Memento restores state that was saved before a
  change, while a command is the change itself, kept until the user agrees.

### Technical debt

Design problems found in review, and what was done about each. Each entry says what the problem was, why it
mattered, what changed, and what shows that behavior was preserved.

#### 1. `gui/views.py` did five jobs (Sprint 4)

- **Problem.** One 1,069-line module held HTTP handling, the Schedule Viewer's meeting data, the weekly calendar
  layout, the overlap-lane algorithm and the Time Slots pages. The meeting data was built as untyped dictionaries
  that the lane code then changed in place. This also contradicted the layer table above, which says views are thin
  request handlers.
- **Why it mattered.** The viewer's rules (which room a lab meeting uses, how a missing room is labelled, how a
  schedule is grouped) could only be reached through private helpers of a view module, so nothing else could share
  them and they could only be tested by importing `gui.views`. A wrong dictionary key failed at run time in a
  template, not in the type check.
- **What changed.**
  - The meeting data moved to the Model: `app/schedule_view.py` turns a schedule into frozen `MeetingBlock` records
    and holds the grouping rules as strategies (above). Rooms and labs are identified by kind and name
    (`Resource`), and sections with no meeting times are reported by `unscheduled_sections`.
  - The calendar layout and the lane algorithm moved to `gui/calendar_layout.py`, which has no Django imports and
    returns typed records (`ScheduleGrid`, `DayColumn`, `PositionedBlock`) built once instead of dictionaries edited
    in place.
  - The Time Slots pages moved to `gui/views_timeslots.py`, next to the other `views_<area>.py` modules.
  - `gui/views.py` went from 1,069 lines to about 600 (it is about 690 now, because the lock panels live there). For the viewer it now only reads the address and builds the
    links that keep the user's choices.
- **Evidence that behavior is preserved.** Before any code moved, the calendar data for a deliberately awkward
  schedule (overlapping meetings, a room and a lab that share a name, missing room, lab and faculty member, an
  online section) was captured from the old code in every view, with and without picked items, in both clock
  formats. `tests/test_calendar_characterization.py` requires the new code to reproduce that capture exactly
  (`tests/calendar_characterization.json`). The viewer page tests that go through Django's test client
  (`tests/test_gui_schedule_room_view.py`, `tests/test_gui_schedule_export_json.py`, `tests/test_gui_timeslots.py`)
  are unchanged apart from where the helpers they call are imported from and reading typed records instead of
  dictionary keys. The schedule viewer template was not edited.

#### 2. The assistant's confirm flows were written twice (Sprint 4)

- **Problem.** `gui/ai/changes.py` (`_Pending`, `confirm_delete`, `cancel_delete`) and `gui/ai/generation.py` (`_Plan`,
  `confirm_schedule_generation`, `cancel_schedule_generation`) each carried their own copy of the same flow: is
  anything waiting, was it asked in this same message, has it expired, is it still what was described. Each kept its
  request in a raw string-keyed attribute on the session and cleared it by hand, and `generation.py` imported a
  private name from `changes.py` to share the request token.
- **Why it mattered.** A change to the rules (for example how long a request may wait, or what makes it stale) had to
  be made in two places, and the two could drift apart. The state lived in loose attributes, so nothing showed which
  things could be waiting or how they were cleared.
- **What changed.** The flow is written once in `gui/ai/pending.py` as the Command pattern (see
  [Command](#command-pending-actions--new-in-sprint-4)). `PendingDelete` and `PendingGeneration` hold what differs (their
  messages, what makes them stale, what running them does); `confirm`, `take`, `stage` and `forget` are the shared
  steps. The request token moved there too, so neither module imports from the other for it.
- **Evidence that behavior is preserved.** The messages, the order of the checks and the session slots are unchanged,
  so `tests/test_ai_changes.py`, `tests/test_ai_generation.py`, `tests/test_ai_clarify.py`, `tests/test_ai_chats.py` and
  `tests/test_ai_config_lifecycle.py`, which read those slots and age them with the modules' own clocks, were not edited.
  `tests/test_ai_pending.py` adds tests for the shared flow and for both commands.

#### 3. The faculty export was built twice (Sprint 4)

- **Problem.** Two Model modules arranged one schedule faculty member by faculty member for a printed export:
  `app/faculty_export.py` (`faculty_export`, `FacultySchedule`, `FacultyMeetingRow`, issue #167) and
  `app/schedule_export.py` (`build_export(..., "faculty")`, issue #164), merged a day apart. The renderer
  (`gui/schedule_pdf.py`) and the PDF controller (`gui/controllers/pdf_export.py`) use only `schedule_export.py`;
  nothing imported `faculty_export.py` except its own tests.
- **Why it mattered.** The same rules (how meetings merge into rows, row order, how a missing room or faculty member
  is labelled, what happens to a section with no meeting times) lived in two places with two sets of record types, so
  a fix to one would silently miss the other, and a reader could not tell which one the PDF used. Its 109 lines also
  counted toward Model coverage while doing nothing in the application.
- **What changed.** `app/faculty_export.py` and `tests/test_faculty_export.py` were removed, along with the module's
  entry in the coverage list in `pyproject.toml`. `app/schedule_export.py` is the one source of export content for both
  orientations.
- **Evidence that behavior is preserved.** No application code imported the removed module, so nothing that runs
  changed; `uv run ty check` confirms no import of it remains. Every rule its tests covered is covered for the faculty
  orientation in `tests/test_schedule_export_data.py`: one section per person in name order with the unassigned last,
  the row details, "No room assigned" instead of an invented room, sections with no meeting times keeping their room or
  lab, one row for the same place and time on several days, row order, a course with no section part, and the schedule
  being unchanged and the records immutable. The one behavior that differs is deliberate: choosing a faculty member
  who teaches nothing is a clear error in `build_export` (decided in the review of #180), where the removed module
  returned an empty section. `tests/test_schedule_pdf.py` checks the faculty PDF built from `schedule_export.py`.

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

Coverage measures team-written code in `app/`: `app.commands.common`, `app.crud`, `app.generation_job`, `app.history`, `app.lock_solver`, `app.locks`, `app.memento`, `app.schedule_io`, `app.schedule_export`, `app.schedule_ops`, `app.schedule_view`, and `app.session` (the list in `pyproject.toml`). `app.commands.common` is included because its shared edit helper is used by both the CLI and GUI; its prompt helpers are included as part of that module. Third-party scheduler-library code is outside the target. Coverage is line coverage and fails below 80%; reproduce it locally with `uv run pytest --cov --cov-report=xml`. CI uploads the XML report to Codecov. No OpenAI secret is needed for routine tests. The tests live in `tests/`: `test_crud_*` and `test_schedule_*` cover the model and CLI layer, `test_gui_*` cover the controllers and pages through Django's test client, `test_lock*`, `test_locks*`, `test_session_locks.py` and `test_generation_locks.py` cover locking (`test_locks_real_solver.py` runs the real solver), and `test_ai_*` cover the assistant with a fake AI.

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
| One schedule as meetings in calendar order (course, section, faculty, room or lab with its kind, day, times) | `meeting_blocks(assignments)` → `MeetingBlock`; `unscheduled_sections(assignments)`; `resources_in(blocks)` | `app/schedule_view.py` |
| Read a schedule by course, room/lab or faculty (labels, picker choices, filtering) | `GROUPINGS[key]` or `grouping_for(key)` → `Grouping` | same |
| Arrange a schedule into export sections, by room or lab or by faculty, for all groups or one | `build_export(assignments, orientation, selected=None)` → `ScheduleExport`; `available_groups(assignments, orientation)`; raises `ExportError` | `app/schedule_export.py` |
| Lay a schedule out as the weekly calendar | `schedule_grid(assignments, view_mode, resources, time_format)` → `ScheduleGrid` | `gui/calendar_layout.py` |
| Build a download (one schedule or all, JSON or CSV) | `export_schedules(request, index_or_None, "json"\|"csv")` → `ExportFile` | `gui/controllers/schedule_controller.py` |
| Read or change the session's locks (one section, one instructor's, several at once, all) | `locked_assignments`, `locked_entries`, `section_states`, `lock_section`, `lock_faculty`, `unlock_section`, `unlock_faculty`, `clear_all`, and the all-or-nothing `lock_sections` / `unlock_sections` | `gui/controllers/locks.py` |
| Hold locks, or spot locks that clash | `LockSet`, `Lock`, `find_conflicts(assignments)` | `app/locks.py` |
| Turn locks into solver rules, and check a result keeps them | `plan_locks`, `apply_plan`, `unkept_locks` | `app/lock_solver.py` |
| Build a PDF of one schedule, and the viewer's list of what it can be exported as | `export_pdf(request, index, orientation, selected, render)` → `PdfFile`; `export_choices(request, index)`; `parse_choice(value)` | `gui/controllers/pdf_export.py` |
| Read an uploaded file (empty/unreadable/too large handled) | `read_upload(uploaded_file, "field_name")` | `gui/controllers/uploads.py` |
| Report a fixable problem on a form | `raise ControllerError([FieldError("field", "message")])` | `gui/controllers/errors.py` |
| "Tick to confirm" before replacing or discarding data | `ConfirmReplaceMixin` + `require_confirmation(...)` | `gui/forms.py` |
| Send a file download | `download_response(filename, content, content_type, download_token(request))` | `gui/views.py` |
| Show a loading state on submit (and ignore double clicks) | `<form ... data-loading="Generating schedules…">`, plus `data-loading-download` for downloads | `gui/static/gui/js/loading.js` |
| Render a whole form (errors + every field) | `{% include "gui/components/form_fields.html" with form=my_form %}` | `gui/templates/gui/components/` |
| "No configuration" actions on an empty page | `{% include "gui/components/no_config_actions.html" %}` | same |
