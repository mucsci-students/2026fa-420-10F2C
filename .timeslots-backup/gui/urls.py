from django.urls import path

from . import views

app_name = "gui"

urlpatterns = [
    path("", views.index, name="index"),
    path("configuration/", views.config_editor, name="config_editor"),
    path("generate/", views.schedule_generator, name="schedule_generator"),
    path("schedules/", views.schedule_viewer, name="schedule_viewer"),
]
