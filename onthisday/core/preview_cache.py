"""How much space the saved previews take, and deleting them.

The previews in the thumbnail folder are what the gallery shows while the library's drive is
disconnected, so deleting them is the user's call, made from Settings. Both functions walk a
folder that can hold 100,000+ files: call them off the UI thread.
"""

import os
import threading
from dataclasses import dataclass

from . import media

# Previews, markers for files that couldn't be read, and leftovers of interrupted writes.
CACHE_SUFFIXES = (".jpg", ".failed", ".part")


@dataclass(frozen=True, slots=True)
class CacheUsage:
    size: int   # bytes
    files: int


def _cache_entries():
    try:
        with os.scandir(media.THUMBNAIL_DIR) as entries:
            for entry in entries:
                if entry.name.endswith(CACHE_SUFFIXES) and entry.is_file(follow_symlinks=False):
                    yield entry
    except FileNotFoundError:
        return


def cache_usage() -> CacheUsage:
    size = files = 0
    for entry in _cache_entries():
        try:
            size += entry.stat(follow_symlinks=False).st_size
        except OSError:
            continue
        files += 1
    return CacheUsage(size, files)


def delete_previews(stop_event: threading.Event | None = None) -> CacheUsage:
    """Delete every saved preview. Returns what was freed (less, if stopped part-way)."""
    size = files = 0
    for entry in list(_cache_entries()):
        if stop_event is not None and stop_event.is_set():
            break
        try:
            entry_size = entry.stat(follow_symlinks=False).st_size
            os.unlink(entry.path)
        except OSError:
            continue  # already gone, or in use on Windows
        size += entry_size
        files += 1
    return CacheUsage(size, files)
