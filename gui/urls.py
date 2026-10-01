from django.urls import path

from . import views, views_labs, views_rooms

app_name = "gui"

urlpatterns = [
    path("", views.index, name="index"),
    path("configuration/", views.config_editor, name="config_editor"),
    path("configuration/new/", views.config_new, name="config_new"),
    path("configuration/load/", views.config_load, name="config_load"),
    path("configuration/save/", views.config_save, name="config_save"),
    path("configuration/validate/", views.config_validate, name="config_validate"),
    path("configuration/timeslots/", views.timeslots, name="timeslots"),
    path("configuration/timeslots/add/", views.timeslot_add, name="timeslot_add"),
    path("configuration/timeslots/options/", views.timing_options, name="timing_options"),
    path("configuration/timeslots/<str:day>/<int:index>/edit/", views.timeslot_edit, name="timeslot_edit"),
    path("configuration/timeslots/<str:day>/<int:index>/delete/", views.timeslot_delete, name="timeslot_delete"),
    path("configuration/rooms/", views_rooms.rooms, name="rooms"),
    path("configuration/rooms/add/", views_rooms.room_add, name="room_add"),
    path("configuration/rooms/<path:room_name>/edit/", views_rooms.room_edit, name="room_edit"),
    path("configuration/rooms/<path:room_name>/delete/", views_rooms.room_delete, name="room_delete"),
    path("configuration/labs/", views_labs.labs, name="labs"),
    path("configuration/labs/add/", views_labs.lab_add, name="lab_add"),
    path("configuration/labs/<path:lab_name>/edit/", views_labs.lab_edit, name="lab_edit"),
    path("configuration/labs/<path:lab_name>/delete/", views_labs.lab_delete, name="lab_delete"),
    path("generate/", views.schedule_generator, name="schedule_generator"),
    path("schedules/", views.schedule_viewer, name="schedule_viewer"),
    path("schedules/import/", views.schedule_import, name="schedule_import"),
]
