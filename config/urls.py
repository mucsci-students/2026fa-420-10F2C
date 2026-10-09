from django.urls import include, path

urlpatterns = [
    path("", include("gui.urls")),
]

# Friendly error pages when DEBUG is off (with DEBUG on, gui/middleware.py
# shows the same friendly page for crashes inside the app).
handler404 = "gui.views_errors.page_not_found"
handler500 = "gui.views_errors.server_error"
