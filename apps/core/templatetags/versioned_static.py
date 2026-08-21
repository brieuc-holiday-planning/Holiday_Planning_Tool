"""`{% vstatic %}` - {% static %} plus a content-version query string.

The dev server serves static files without a Cache-Control header, so a
browser is free to keep using a script or stylesheet it already has. That
makes edits to our own CSS/JS invisible until a hard refresh, which is a
genuinely confusing failure mode: the page looks updated (templates are
never cached) while the behaviour behind it is still the old file.

Appending the file's modification time makes the URL change whenever the
file does, so the browser always fetches the current version.
"""

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

import os

register = template.Library()

_version_cache = {}


@register.simple_tag
def vstatic(path):
    from django.conf import settings

    url = static(path)
    # In production collectstatic already puts a content hash in the
    # filename (see config.settings.prod STORAGES), which busts caches
    # properly - adding a query string on top would be redundant and can
    # stop some CDNs caching at all.
    if not settings.DEBUG:
        return url

    version = _file_version(path)
    if not version:
        return url
    return f"{url}{'&' if '?' in url else '?'}v={version}"


def _file_version(path):
    """Modification time of the source file, or None if it can't be found
    (e.g. served from a remote storage backend, where the URL is already
    expected to be versioned)."""
    if path in _version_cache:
        return _version_cache[path]

    version = None
    try:
        absolute_path = finders.find(path)
        if absolute_path:
            version = int(os.path.getmtime(absolute_path))
    except (OSError, ValueError):
        version = None

    # Only cache once resolved; in DEBUG the mtime is re-read every render so
    # editing a file takes effect on the next page load without a restart.
    from django.conf import settings

    if not settings.DEBUG:
        _version_cache[path] = version
    return version
