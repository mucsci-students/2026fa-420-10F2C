"""Shared view helper for rename propagation confirmations.

Each configuration controller decides which records must change. This helper
only renders the common confirmation UI and signs the already-validated form
data that the resource-specific confirmation endpoint will apply.
"""

from django.shortcuts import render

from gui.rename_confirmation import create_rename_confirmation


def render_rename_confirmation(
    request,
    *,
    resource_key: str,
    resource_label: str,
    collection_label: str,
    list_url_name: str,
    identifier: str | int,
    old_name: str,
    new_name: str,
    references: list[str],
    form_data: dict,
    confirm_url_name: str,
    cancel_url_name: str,
):
    """Render the shared page for a reviewed rename and its affected records."""
    return render(
        request,
        "gui/rename_confirm.html",
        {
            "active": "config",
            "resource_label": resource_label,
            "collection_label": collection_label,
            "list_url_name": list_url_name,
            "identifier": identifier,
            "old_name": old_name,
            "new_name": new_name,
            "references": references,
            "confirmation_token": create_rename_confirmation(resource_key, identifier, form_data),
            "confirm_url_name": confirm_url_name,
            "cancel_url_name": cancel_url_name,
        },
    )