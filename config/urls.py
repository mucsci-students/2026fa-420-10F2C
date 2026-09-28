from django.urls import include, path

urlpatterns = [
    path("", include("gui.urls")),
]
