from django.urls import path

from . import views

app_name = "gui"

urlpatterns = [
    path("", views.index, name="index"),
    path("configuration/", views.config_editor, name="config_editor"),
    path("configuration/timeslots/", views.timeslots, name="timeslots"),
    path("configuration/timeslots/add/", views.timeslot_add, name="timeslot_add"),
    path("configuration/timeslots/options/", views.timing_options, name="timing_options"),
    path("configuration/timeslots/<str:day>/<int:index>/edit/", views.timeslot_edit, name="timeslot_edit"),
    path("configuration/timeslots/<str:day>/<int:index>/delete/", views.timeslot_delete, name="timeslot_delete"),
    path("generate/", views.schedule_generator, name="schedule_generator"),
    path("schedules/", views.schedule_viewer, name="schedule_viewer"),
    path("schedules/import/", views.schedule_import, name="schedule_import"),
    path("schedules/export/json/", views.schedule_export_json, name="schedule_export_json"),
]
