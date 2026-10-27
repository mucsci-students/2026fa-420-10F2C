"""
{% versioned 'gui/css/style.css' %} -> /static/gui/css/style.css?v=1761600000

A browser may keep using an old copy of a stylesheet or script for days, because the development
server sends no cache instructions and browsers then guess. After an update the page would be drawn
with the new script and the old stylesheet (broken layout). The number is the file's last-changed
time, so the address changes exactly when the file does and the browser fetches the new copy.
"""

import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def versioned(path: str) -> str:
    url = static(path)
    try:
        found = finders.find(path)
        if isinstance(found, (list, tuple)):
            found = found[0] if found else None
        if found:
            return f"{url}?v={int(os.path.getmtime(found))}"
    except OSError, ValueError:
        pass
    return url
