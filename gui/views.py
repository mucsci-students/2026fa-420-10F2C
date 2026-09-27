"""
View layer (Section 20: View = "GUI pages, forms, tables, components,
dialogs, navigation, and user-facing messages"). Views stay thin: parse the
request, call a controller, render a template with what the controller
returns. Scheduler-domain logic and validation stay out of this file --
see gui/controllers/ and app/.

index/config_editor/schedule_generator/schedule_viewer below render real
pages today (not stubs) so navigation (Section 4) works end to end; each
non-home page's template lists what that mode still needs (see
gui/templates/gui/*.html). As controllers/forms get implemented, these
view functions will start calling them instead of just rendering a static
template.
"""

from django.shortcuts import render


def index(request):
    """Welcome screen -- links to the three required modes (Section 1)."""
    return render(request, "gui/index.html", {"active": "home"})


def config_editor(request):
    """Configuration Editor mode (Sections 6-12). Placeholder page today;
    see gui/controllers/config_controller.py and crud_controller.py for
    what still needs wiring in."""
    return render(request, "gui/config_editor.html", {"active": "config"})


def schedule_generator(request):
    """Schedule Generator mode (Sections 13-14). Placeholder page today;
    see gui/controllers/schedule_controller.py."""
    return render(request, "gui/schedule_generator.html", {"active": "generator"})


def schedule_viewer(request):
    """Schedule Viewer mode (Sections 15-18). Placeholder page today;
    see gui/controllers/schedule_controller.py."""
    return render(request, "gui/schedule_viewer.html", {"active": "viewer"})
