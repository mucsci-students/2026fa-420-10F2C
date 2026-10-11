#!/usr/bin/env bash
# =============================================================================
#  cleanup_dev_notes.sh
#
#  Removes developer-facing leftovers that a client would otherwise see:
#
#    Config Editor page   "In progress" badge; "(Sections 6-12)" in the intro;
#                         the unreachable "Coming soon" card branch
#    Schedule Viewer page "In progress" badge; "(Sections 15-18)" in the intro
#    Home page            "Sprint 2 requires three clearly identifiable modes
#                         (Section 1):" intro, and the "Status: navigation and
#                         page structure are in place..." note
#    gui/views.py         stale "when an area's pages exist" comment, and the
#                         "no URL" fallback that can no longer happen
#    gui/forms.py         stale TODO for GenerationOverrideForm (it exists);
#                         docstring list indentation tidied
#    schedule_controller  the unused view_schedule() stub that raised
#                         NotImplementedError (and its docstring line)
#    style.css            .badge and .area-card--soon rules, now unused
#
#  Usage (from the repository root):
#      bash cleanup_dev_notes.sh                # patch ., then run the tests
#      bash cleanup_dev_notes.sh /path/to/repo
#      bash cleanup_dev_notes.sh --no-tests
#
#  Safe: every pattern must match exactly once or NOTHING is written. Running
#  it a second time just reports that there is nothing left to do. Nothing is
#  committed; review with `git diff`.
# =============================================================================
set -euo pipefail

RUN_TESTS=1
REPO=""
for arg in "$@"; do
  case "$arg" in
    --no-tests) RUN_TESTS=0 ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) REPO="$arg" ;;
  esac
done
REPO="$(cd "${REPO:-$PWD}" && pwd)"

for f in gui/templates/gui/config_editor.html gui/templates/gui/schedule_viewer.html \
         gui/templates/gui/index.html gui/views.py gui/forms.py \
         gui/controllers/schedule_controller.py gui/static/gui/css/style.css; do
  [ -f "$REPO/$f" ] || { echo "ERROR: $f not found. Run from the repository root (or pass its path)." >&2; exit 1; }
done

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
[ -n "$PY" ] || { echo "ERROR: Python 3 is required to apply the patch." >&2; exit 1; }

"$PY" - "$REPO" <<'PYEOF'
import re
import sys
from pathlib import Path

repo = Path(sys.argv[1])
M, S = re.MULTILINE, re.DOTALL

CFG = "gui/templates/gui/config_editor.html"
VIEWER = "gui/templates/gui/schedule_viewer.html"
INDEX = "gui/templates/gui/index.html"
VIEWS = "gui/views.py"
FORMS = "gui/forms.py"
CTRL = "gui/controllers/schedule_controller.py"
CSS = "gui/static/gui/css/style.css"

# (label, file, regex, replacement, flags). Each regex must match exactly once.
STEPS = [
    # ---- Configuration Editor page ----------------------------------------
    ("config page: 'In progress' badge", CFG,
     r'<h1>Configuration Editor <span class="badge">In progress</span></h1>',
     '<h1>Configuration Editor</h1>', 0),
    ("config page: '(Sections 6-12)' in the intro", CFG,
     r'modify a complete scheduler configuration \(Sections 6&ndash;12\)\.',
     'modify a complete scheduler configuration.', 0),
    ("config page: 'Coming soon' branch, opening if", CFG,
     r'    \{% if area\.url %\}\n(    <a class="area-card" href="\{\{ area\.url \}\}">)',
     r'\1', 0),
    ("config page: 'Coming soon' branch, else block", CFG,
     r'    </a>\n    \{% else %\}\n    <div class="area-card area-card--soon">.*?</div>\n    \{% endif %\}\n    \{% endfor %\}',
     '    </a>\n    {% endfor %}', S),

    # ---- Schedule Viewer page ---------------------------------------------
    ("viewer page: 'In progress' badge", VIEWER,
     r'<h1>Schedule Viewer <span class="badge">In progress</span></h1>',
     '<h1>Schedule Viewer</h1>', 0),
    ("viewer page: '(Sections 15-18)' in the intro", VIEWER,
     r'readable format \(Sections 15&ndash;18\)\.',
     'readable format.', 0),

    # ---- Home page ---------------------------------------------------------
    ("home page: 'Sprint 2 requires ... (Section 1)' intro", INDEX,
     r'<p class="page-intro">Sprint 2 requires three clearly identifiable modes \(Section 1\):</p>',
     '<p class="page-intro">Choose a mode to get started:</p>', 0),
    ("home page: 'Status: navigation and page structure...' note", INDEX,
     r'<p class="help"><em>Status: navigation and page structure are in place\..*?</em></p>\n',
     '', S),

    # ---- gui/views.py -------------------------------------------------------
    ("views.py: stale _CONFIG_AREAS comment", VIEWS,
     r'(# config_controller\.describe_configuration, label, URL name)\)\. When an area\'s\n'
     r'# pages exist, put its URL name here -- that is the only change the home page\n'
     r'# needs to link to it\.\n',
     r'\1).\n', 0),
    ("views.py: unreachable 'no URL' fallback", VIEWS,
     r'"url": reverse\(url_name\) if url_name else None\}',
     '"url": reverse(url_name)}', 0),

    # ---- gui/forms.py -------------------------------------------------------
    ("forms.py: dedent FacultyForm docstring line", FORMS,
     r'^        - FacultyForm \(', '    - FacultyForm (', M),
    ("forms.py: dedent CourseForm docstring line", FORMS,
     r'^        - CourseForm \(', '    - CourseForm (', M),
    ("forms.py: stale TODO for GenerationOverrideForm", FORMS,
     r'\n\nTODO: one Form class per remaining area.*?\n"""\n',
     '\n    - GenerationOverrideForm (Schedule Generator: one-run generation limit and\n'
     '      optimizer overrides; kept apart from GlobalSettingsForm because they\n'
     '      must NOT touch the saved configuration)\n"""\n', S),

    # ---- schedule_controller.py --------------------------------------------
    ("schedule_controller: docstring line for the removed stub", CTRL,
     r'^    view_schedule\(\)     -> get_schedule\(request, index\), then group by room/faculty\n',
     '', M),
    ("schedule_controller: unused view_schedule() stub", CTRL,
     r'\n\ndef view_schedule\(request, index\):\n    """TODO \(Section 15-16\).*?    raise NotImplementedError\n',
     '', S),

    # ---- style.css ----------------------------------------------------------
    ("css: unused .badge rule", CSS,
     r'^\.badge \{[^}]*\}\n\n', '', M),
    ("css: unused dark-mode .badge rule", CSS,
     r'^html\[data-theme="dark"\] \.badge \{[^}]*\}\n', '', M),
    ("css: unused .area-card--soon rules", CSS,
     r'^\.area-card--soon \{[^}]*\}\n\n\.area-card--soon \.area-card__count \{[^}]*\}\n\n', '', M),
]

texts = {}
def current(path):
    if path not in texts:
        texts[path] = (repo / path).read_text(encoding="utf-8")
    return texts[path]

originals = {}
counts = []
for label, path, pattern, replacement, flags in STEPS:
    text = current(path)
    originals.setdefault(path, text)
    counts.append((label, len(re.findall(pattern, text, flags))))

if all(n == 0 for _, n in counts):
    print("Nothing to do: all of these leftovers are already gone.")
    sys.exit(0)

bad = [(label, n) for label, n in counts if n != 1]
if bad:
    print("Nothing was changed. These parts did not match exactly once:\n", file=sys.stderr)
    for label, n in bad:
        print(f"  - {label}: found {n}", file=sys.stderr)
    print("\nYour local files differ from what this script expects (git pull, then retry).", file=sys.stderr)
    sys.exit(1)

for label, path, pattern, replacement, flags in STEPS:
    texts[path] = re.sub(pattern, replacement, texts[path], count=1, flags=flags)

# ---- sanity checks before writing anything ---------------------------------
problems = []
for path in (CFG, VIEWER, INDEX):
    before, after = originals[path], texts[path]
    for tag in ("{% if ", "{% endif %}", "{% for ", "{% endfor %}", "{% block ", "{% endblock %}"):
        removed = before.count(tag) - after.count(tag)
        if tag in ("{% if ", "{% endif %}") and path == CFG:
            if removed != 1:
                problems.append(f"{path}: expected exactly one {tag.strip()} removed, saw {removed}")
        elif removed != 0:
            problems.append(f"{path}: {tag.strip()} count changed unexpectedly ({removed})")

leftovers = {
    CFG: ["In progress", "Sections 6", "Coming soon", "area--soon"],
    VIEWER: ["In progress", "Sections 15"],
    INDEX: ["Sprint 2 requires", "Status: navigation"],
    FORMS: ["TODO"],
    CTRL: ["NotImplementedError", "def view_schedule"],
    CSS: [".badge", "area-card--soon"],
}
for path, needles in leftovers.items():
    for needle in needles:
        if needle in texts[path]:
            problems.append(f"{path}: still contains {needle!r}")

if problems:
    print("Nothing was changed:\n", file=sys.stderr)
    for p in problems:
        print("  - " + p, file=sys.stderr)
    sys.exit(1)

for path, text in texts.items():
    (repo / path).write_text(text, encoding="utf-8")
    print(f"  patched  {path}")
PYEOF

echo
echo "Checking syntax..."
"$PY" -m py_compile "$REPO/gui/views.py" "$REPO/gui/forms.py" "$REPO/gui/controllers/schedule_controller.py"
echo "OK"

if [ "$RUN_TESTS" -eq 1 ]; then
  if command -v uv >/dev/null 2>&1; then
    echo
    echo "Running the test suite..."
    (cd "$REPO" && uv run pytest -q)
  else
    echo
    echo "uv not found - skipping tests. Run:  uv run pytest"
  fi
fi

echo
echo "Done. Look over: Home, Configuration Editor and Schedule Viewer pages."
echo "Review the changes with:  git diff"