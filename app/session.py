# ----------------------------------------------------------------------------------------------------------------------- #
#   app/session.py                                                                                                        #
#                                                                                                                         #
#   Backbone piece #1: the shell needs ONE object that lives for the whole                                              #
#   process and holds the in-memory CombinedConfig plus generated schedules.                                             #
#                                                                                                                         #
#   Satisfies:                                                                                                          #
#     Req #3 (persistent session, work with config in memory across actions)                                             #
#     Req #4 (load/save/inspect/validate; a bad load must not clobber a good                                             #
#             in-memory config)                                                                                          #
#     Req #9 (generated schedules available for inspection during the session)                                          #
#                                                                                                                         #
#   CONFIRMED from `uv run python -c "import scheduler.config as c; ..."`:                                               #
#     scheduler.config exports ValidationError -- narrowed the except clauses            #
#     below to it instead of a bare Exception.                                                                          #
#                                                                                                                         #
#   STILL UNCONFIRMED -- new_config()'s seed data below:                                                                 #
#   `CombinedConfig(config={"rooms": [], ...})` raised 9 pydantic ValidationErrors        #
#   requiring >=1 room/course/faculty, a time block for every weekday, and               #
#   >=1 class pattern -- an empty config is not a valid CombinedConfig. The              #
#   seed values below are my best reconstruction from the JSON shapes seen               #
#   in the Sprint 1 slides/docs (course_id, credits, room/lab lists, times as             #
#   {"start","spacing","end"}, meetings as {"day","duration","lab"}, etc.), NOT           #
#   verified field-by-field against the installed package. Before trusting               #
#   this, run:                                                                          #
#                                                                                         #
#     uv run python -c "                                                                #
#     from scheduler.config import CombinedConfig                                        #
#     import json                                                                       #
#     print(json.dumps(CombinedConfig.model_json_schema(), indent=2))                    #
#     " | less                                                                           #
#                                                                                         #
#   and adjust every dict below to match what the schema actually requires               #
#   (field names, required-ness, enum values for modality/delivery mode, etc).            #
# ----------------------------------------------------------------------------------------------------------------------- #

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Optional

from scheduler import load_config_from_file
from scheduler.config import CombinedConfig, ValidationError


class ConfigError(Exception):
    """Raised for any problem creating/loading/saving a configuration.
    The shell should catch this, print e, and keep running -- never let it
    propagate out of handle_command()."""


# A minimal-but-valid seed config. Used by Session.new_config() as the
# starting point a user then edits via CRUD, since CombinedConfig has no
# concept of an "empty" valid state (see CONFIRM block above).
#
# NOTE: field names/shapes here are reconstructed from documented JSON
# examples, not verified against CombinedConfig.model_json_schema(). Treat
# every key below as a guess to double-check, not a fact.
_MINIMAL_SEED_CONFIG = {
    "rooms": [
        {"name": "Placeholder Room", "capacity": 30, "features": []},
    ],
    "labs": [],
    "courses": [
        {
            "course_id": "PLACEHOLDER 000",
            "credits": 3,
            "capacity": 30,
            "room": ["Placeholder Room"],
            "lab": [],
            "conflicts": [],
            "faculty": ["Placeholder Faculty"],
        },
    ],
    "faculty": [
        {
            "name": "Placeholder Faculty",
            "maximum_credits": 12,
            "minimum_credits": 0,
            "unique_course_limit": 2,
            "times": {
                "MON": ["09:00-17:00"],
                "TUE": ["09:00-17:00"],
                "WED": ["09:00-17:00"],
                "THU": ["09:00-17:00"],
                "FRI": ["09:00-17:00"],
            },
            "course_preferences": {},
            "room_preferences": {},
            "lab_preferences": {},
        },
    ],
}

_MINIMAL_SEED_TIME_SLOT_CONFIG = {
    "times": {
        day: [{"start": "09:00", "spacing": 60, "end": "17:00"}]
        for day in ("MON", "TUE", "WED", "THU", "FRI")
    },
    "classes": [
        {
            "credits": 3,
            "meetings": [{"day": "MON", "duration": 150, "lab": False}],
        },
    ],
}


class Session:
    """One instance of this lives inside SchedulerShell for the whole run.
    Every command function should take `session` as its first argument
    instead of doing its own file I/O."""

    def __init__(self) -> None:
        self.config: Optional[CombinedConfig] = None
        self.config_path: Optional[Path] = None
        # Display name of the file the config was last loaded from or saved as
        # (the web GUI has no real path for an upload, only a name). Used to
        # name the Save download. None for a new, never-saved configuration.
        self.config_name: Optional[str] = None
        # Each generated schedule is whatever Scheduler.get_models() yields
        # (a list of CourseInstance, per the library's Python API docs).
        # Kept as a plain list so "schedule summary/view/clear" (Req #9)
        # have something to index into.
        self.schedules: list = []
        # True whenever the in-memory config has changes not yet written
        # to disk. Set by commands.py's _apply_edit() wrapper on every
        # successful add/modify/delete; cleared here on new/load/save so
        # the shell can warn before exiting or discarding unsaved work.
        self.dirty: bool = False

    # ---------------------------------------------------------------- #
    #  Configuration lifecycle (Req #4)                                #
    # ---------------------------------------------------------------- #
    def new_config(self) -> None:
        """Start a fresh, minimal-but-valid in-memory configuration
        (Req #4: 'create a new scheduler configuration'). See the
        _MINIMAL_SEED_* constants above -- an empty config is not
        accepted by CombinedConfig, so this seeds one placeholder room/
        course/faculty/class-pattern the user is expected to edit or
        delete via CRUD once real data exists."""
        try:
            self.config = CombinedConfig(
                config=_MINIMAL_SEED_CONFIG,
                time_slot_config=_MINIMAL_SEED_TIME_SLOT_CONFIG,
            )
        except ValidationError as e:
            raise ConfigError(f"Could not create new configuration: {e}") from e

        self.config_path = None
        self.config_name = None
        self.schedules = []
        self.dirty = False

    def load(self, path: str) -> None:
        """Load + validate a configuration file through the library
        (Req #4). On ANY failure -- missing file, invalid JSON, invalid
        schema data -- the previously valid in-memory config is left
        completely untouched, and a ConfigError with a readable message is
        raised for the shell to print."""
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"No such file: {p}")

        try:
            new_config = load_config_from_file(CombinedConfig, str(p))
        except ValidationError as e:
            raise ConfigError(f"Could not load '{p}': {e}") from e
        except (OSError, ValueError) as e:
            # bad JSON / unreadable file -- distinct from a schema
            # validation failure, but still a "don't touch prior state"
            # case per Req #4.
            raise ConfigError(f"Could not read '{p}': {e}") from e

        # Only swap state in after a fully successful load+validate.
        self.config = new_config
        self.config_path = p
        self.config_name = p.name
        self.schedules = []
        self.dirty = False

    def save(self, path: Optional[str] = None) -> Path:
        """Serialize the in-memory config through Pydantic (Req #4: 'saved
        configurations must serialize through the library's supported
        Pydantic serialization mechanism'). Reuses the last load/save path
        if the user just types 'config save' with nothing else."""
        if self.config is None:
            raise ConfigError("No configuration loaded. Try 'config new' or 'config load <path>'.")

        target = Path(path) if path else self.config_path
        if target is None:
            raise ConfigError("No path given, and this config hasn't been saved/loaded from one yet.")

        target.write_text(self.config.model_dump_json(indent=2), encoding="utf-8")
        self.config_path = target
        self.config_name = target.name
        self.dirty = False
        return target

    # ---------------------------------------------------------------- #
    #  Web/GUI helpers (a browser upload is bytes, a download is text) #
    # ---------------------------------------------------------------- #
    def load_bytes(self, raw: bytes, name: str = "the uploaded file") -> None:
        """Load + validate a configuration from raw file bytes, e.g. a
        browser upload. Same all-or-nothing rule as load(): the previous
        config, schedules and dirty flag are only replaced after the
        library has fully validated the new one; any failure raises a
        ConfigError with a readable message and changes nothing.

        The library's own loader only reads paths, so the bytes are written
        to a throwaway folder first; that keeps this on exactly the same
        loading code (and validation) as the CLI's load()."""
        try:
            data = json.loads(raw)
        except UnicodeDecodeError as e:
            raise ConfigError(f"'{name}' is not a text file (it is not valid UTF-8).") from e
        except json.JSONDecodeError as e:
            raise ConfigError(
                f"'{name}' is not valid JSON: {e.msg} (line {e.lineno}, column {e.colno})."
            ) from e
        if not isinstance(data, dict):
            raise ConfigError(f"'{name}' must contain a JSON object, like the files saved by this app.")

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "configuration.json"
            path.write_bytes(raw)
            try:
                new_config = load_config_from_file(CombinedConfig, str(path))
            except ValidationError as e:
                raise ConfigError(f"'{name}' is not a valid configuration.") from e
            except (OSError, ValueError) as e:
                raise ConfigError(f"Could not read '{name}': {e}") from e

        # Only swap state in after a fully successful load+validate.
        self.config = new_config
        self.config_path = None  # an upload has no path on this machine
        self.config_name = Path(name).name or None
        self.schedules = []
        self.dirty = False

    def dumps(self) -> str:
        """The in-memory config as JSON text, through the library's own
        Pydantic serialization (the same text save() writes to disk)."""
        return self.require_config().model_dump_json(indent=2)

    def mark_saved(self, name: Optional[str] = None) -> None:
        """Record that the current config was handed to the user as a file
        (the GUI's Save download): clears the unsaved-changes flag."""
        self.dirty = False
        if name:
            self.config_name = name

    def require_config(self) -> CombinedConfig:
        """Every CRUD/schedule command should call this first instead of
        assuming self.config exists."""
        if self.config is None:
            raise ConfigError("No configuration loaded. Try 'config new' or 'config load <path>'.")
        return self.config