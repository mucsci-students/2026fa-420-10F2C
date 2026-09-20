# 2026fa-420-10F2C

## Contributors
Calvin Becker
Alan Reider
Henry Malesker
Joseph Lucks
Samsong Tamang
James Liranzo

## Overview

This course scheduler is an interactive command line tool for building, validating, and solving university course scheduling configurations. It wraps the [`course-constraint-scheduler`](https://pypi.org/project/course-constraint-scheduler/) library, which uses the Z3 constraint solver to find schedules that satisfy every hard constraint (faculty availability, room and lab capacity, course conflicts, meeting patterns, and so on).

With it you can:

- **Manage a configuration in memory.** Add, modify, and delete faculty, rooms, labs, time slots, class patterns, and meetings. Every edit re-validates the whole configuration and rolls back automatically if it would make the configuration invalid.
- **Protect against dangling references.** Deleting a room, lab, or faculty member that a course still uses is blocked with a clear message.
- **Load and save configurations** as JSON, with a warning before you discard unsaved changes.
- **Tune the solver.** Set the generation limit and enable or disable optimizer flags.
- **Generate and inspect schedules,** then **export** one or all of them to JSON or CSV.

The shell starts with an example dataset already loaded (`app/examples/config_example.json`), so you can explore right away.

## Prerequisites

- **Python 3.14 or newer** (see `.python-version`)
- **[uv](https://docs.astral.sh/uv/)** for dependency management and running commands
- **Git** to clone the repository

The main runtime dependency is `course-constraint-scheduler >= 3.0.0`, and `pytest` is used for testing. Both are installed for you by `uv` in the steps below.

## Getting Started

1. **Clone the repository**

```bash
   git clone <repository-url>
   cd 2026fa-420-10F2C
```

2. **Install dependencies**

```bash
   uv sync
```

   This creates a virtual environment and installs everything pinned in `uv.lock`.

3. **Run the shell**

```bash
   uv run python main.py
```

4. **Pick an option from the main menu**

```
   1. Configuration
   2. Run Scheduler
   3. View / Export Schedules
   4. Config File (new / load / save / print / validate)
   0. Exit
```

   A typical first session:

   1. Choose **1** to browse or edit faculty, rooms, labs, and other settings.
   2. Choose **2** to generate schedules (leave the limit blank to use the configuration's own).
   3. Choose **3** to view a schedule by index or export results to JSON or CSV.
   4. Choose **4 → Save** to write your configuration to disk before exiting.
