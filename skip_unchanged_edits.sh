#!/usr/bin/env bash
# ============================================================================
#  skip_unchanged_edits.sh
#
#  Submitting an edit form without changing anything no longer adds an entry
#  to the history (so there is nothing to undo or redo), no longer shows an
#  Undo offer, and no longer marks the configuration as having unsaved changes.
#  Redo is kept, because nothing new happened.
#
#  Usage (repository root):  bash skip_unchanged_edits.sh --dry-run ; bash skip_unchanged_edits.sh
#  All-or-nothing; originals are backed up to your temp folder.
# ============================================================================
set -euo pipefail
if [ ! -f manage.py ] || [ ! -d tests ]; then echo "Run this from the repository root (the folder that contains manage.py)." >&2; exit 1; fi
command -v python3 >/dev/null 2>&1 || { echo "python3 is required." >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo "git is required." >&2; exit 1; }
PATCH_FILE="$(mktemp)"; trap 'rm -f "$PATCH_FILE"' EXIT
cat > "$PATCH_FILE" <<'__PATCH__'
diff --git a/app/commands/common.py b/app/commands/common.py
index 19bd1dc..c83f1c6 100644
--- a/app/commands/common.py
+++ b/app/commands/common.py
@@ -25,14 +25,19 @@ def apply_session_edit(session, config, area, mutate_fn: Callable[[object], None
     of the configuration that really changed, so a rejected edit leaves nothing to undo.
     `label` names the change for the Undo button; without one the change is described in
     words (or a generic "Edit <area>").
+
+    An edit that changed nothing (a form submitted with no change) adds nothing to the history
+    and does not mark the configuration as having unsaved changes.
     """
     history = getattr(session, "history", None)
     before = history.capture(config) if history is not None else None
     dirty_before = session.dirty
     apply_edit(config, area, mutate_fn)
+    changed = True
     if history is not None:
-        history.record(label, before, dirty_before, after=config, area=area)
-    session.dirty = True
+        changed = history.record(label, before, dirty_before, after=config, area=area) is not None
+    if changed:
+        session.dirty = True
 
 
 def field_value(obj, key):
diff --git a/app/history.py b/app/history.py
index 2d5fc02..790f971 100644
--- a/app/history.py
+++ b/app/history.py
@@ -110,15 +110,23 @@ class ConfigHistory:
         """Save mementos of every part of `config` (call this BEFORE the edit)."""
         return ConfigOriginator(config).create_memento()
 
-    def record(self, label, before: CompositeMemento, dirty_before: bool, after=None, area=None) -> Snapshot:
+    def record(
+        self, label, before: CompositeMemento, dirty_before: bool, after=None, area=None
+    ) -> Snapshot | None:
         """Remember a successful edit.
 
         `before` is what capture() returned. `after` is the configuration now:
         when it is given, only the parts that really changed are kept and the
         change is described in words. `label` names the change for the Undo
-        button (a description of what changed is used when it is None)."""
+        button (a description of what changed is used when it is None).
+
+        An edit that changed nothing (a form submitted without any change) is
+        not remembered: nothing is added to the history, redo is kept, and None
+        is returned."""
         if after is not None:
             before = before.changed_since(after)
+            if not len(before):
+                return None
             summary = before.describe_change(after)
         else:
             summary = ""
diff --git a/tests/test_history.py b/tests/test_history.py
index 22bb842..5b99703 100644
--- a/tests/test_history.py
+++ b/tests/test_history.py
@@ -7,6 +7,7 @@ fake session stand in, so they exercise only the undo/redo rules themselves.
 
 import pytest
 
+from app.commands.common import apply_session_edit
 from app.history import ConfigHistory, HistoryError
 from tests.fakes import FakeConfig, course, room
 
@@ -227,11 +228,17 @@ def test_an_edit_without_a_label_is_named_after_what_it_changed():
     assert entry.label == "Added room B"
 
 
-def test_an_edit_that_changed_nothing_is_named_after_its_area():
+def test_an_edit_that_changed_nothing_is_not_remembered():
     session = FakeSession()
+    edit(session, "one", ["A", "1"])
+    session.history.undo(session)
+    version = session.history.version
     before = session.history.capture(session.config)
-    entry = session.history.record(None, before, False, after=session.config, area="time_slots")
-    assert entry.label == "Edit time slots" and entry.summary == ""
+    assert session.history.record("Edit room 'A'", before, False, after=session.config) is None
+    assert not session.history.can_undo
+    assert session.history.can_redo                   # redo is kept, as nothing new happened
+    assert session.history.version == version
+    assert session.history.take_fresh() is None       # and no Undo is offered
 
 
 def test_a_very_long_description_is_shortened_for_the_label():
@@ -275,3 +282,23 @@ def test_a_change_to_several_parts_is_one_step():
     session.history.undo(session)
     assert rooms_of(session) == ["A"]
     assert session.config.config.courses == [course("CMSC 140", rooms=["A"])]
+
+
+def test_submitting_an_edit_with_no_change_adds_no_history_and_leaves_the_flag_alone():
+    session = FakeSession()
+    apply_session_edit(session, session.config, "room", lambda draft: None, label="Edit room 'A'")
+    assert not session.history.can_undo and session.dirty is False
+
+    def same_values(draft):
+        draft.config.rooms[:] = [room("A")]      # rewritten, but identical
+
+    apply_session_edit(session, session.config, "room", same_values)
+    assert not session.history.can_undo and session.dirty is False
+
+
+def test_a_real_edit_still_counts():
+    session = FakeSession()
+    apply_session_edit(
+        session, session.config, "room", lambda draft: draft.config.rooms.append(room("B")), label="Add room 'B'"
+    )
+    assert session.history.undo_label == "Add room 'B'" and session.dirty is True
diff --git a/tests/test_history_controller.py b/tests/test_history_controller.py
index b5ce89a..9546ee4 100644
--- a/tests/test_history_controller.py
+++ b/tests/test_history_controller.py
@@ -23,7 +23,7 @@ def session(monkeypatch):
 
 def rename_first_room(session, name):
     def mutate(draft):
-        draft.config.rooms[0].capacity = len(name)
+        draft.config.rooms[0].capacity = sum(map(ord, name))   # a different value for each name
 
     apply_session_edit(session, session.config, "room", mutate, label=name)
 
__PATCH__

python3 - "$PATCH_FILE" "$@" <<'__PY__'
import re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

PATCH = Path(sys.argv[1]); DRY = "--dry-run" in sys.argv[2:]; ROOT = Path.cwd()
text = PATCH.read_text(encoding="utf-8")
files = re.findall(r"^diff --git a/(\S+) b/\S+$", text, re.M)
new_files = re.findall(r"^diff --git a/(\S+) b/\S+\nnew file mode", text, re.M)

def die(msg):
    print(f"\n{msg}\nNOTHING WAS CHANGED."); sys.exit(1)

if not (ROOT / "app/memento.py").exists():
    die("Prerequisite missing: add_memento_pattern.sh has not been applied (no app/memento.py).")
history = (ROOT / "app/history.py").read_text(encoding="utf-8")
if "An edit that changed nothing" in history:
    print("This fix is already applied. Nothing to do."); sys.exit(0)
clash = [p for p in new_files if (ROOT / p).exists()]
if clash:
    die("These files already exist but the upgrade is not applied, so your tree is in an unexpected state:\n  " + "\n  ".join(clash))

T = Path(tempfile.mkdtemp(prefix="noop-tree-"))
for p in files:
    if (ROOT / p).exists():
        (T / p).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(ROOT / p, T / p)
subprocess.run(["git", "init", "-q"], cwd=T, check=True)
for extra in ([], ["-C1"]):
    res = subprocess.run(["git", "apply", "--whitespace=nowarn", *extra, str(PATCH)], cwd=T, capture_output=True, text=True)
    if res.returncode == 0: break
if res.returncode != 0:
    shutil.rmtree(T, ignore_errors=True)
    die("The changes do not fit your files:\n" + res.stderr.strip() +
        "\n\nYour tree differs from the one this upgrade was built against "
        "(the state after add_memento_pattern.sh).")
bad = []
for p in files:
    if p.endswith(".py") and (T / p).exists():
        try: compile((T / p).read_text(encoding="utf-8"), p, "exec")
        except SyntaxError as e: bad.append(f"{p}: {e}")
if bad:
    shutil.rmtree(T, ignore_errors=True); die("Syntax problems after applying:\n  " + "\n  ".join(bad))
print(f"All {len(files)} file changes fit: {len(new_files)} new, {len(files) - len(new_files)} modified.")
if DRY:
    shutil.rmtree(T, ignore_errors=True); print("Dry run: nothing was changed."); sys.exit(0)
backup = Path(tempfile.gettempdir()) / f"scheduler-noop-backup-{time.strftime('%Y%m%d-%H%M%S')}"
for p in files:
    if (ROOT / p).exists():
        (backup / p).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(ROOT / p, backup / p)
touched = []
try:
    for p in files:
        (ROOT / p).parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(T / p, ROOT / p); touched.append(p)
except Exception as exc:
    print(f"\nERROR: {exc}\nRestoring your original files ...")
    for p in touched:
        if (backup / p).exists(): shutil.copyfile(backup / p, ROOT / p)
        elif (ROOT / p).exists(): (ROOT / p).unlink()
    print("Restored. Nothing was changed."); sys.exit(1)
shutil.rmtree(T, ignore_errors=True)
print(f"\nDone. {len(files)} file(s) written. Originals copied to: {backup}")
print("\nNext: uv run pytest     (expected: about 887 passed)")
__PY__