"""Save a preview of every indexed item in the background, so the gallery can show the library
while its drive is disconnected, and scrolling never waits on an original.

Making a preview means decoding the photo or a video frame (tens to hundreds of milliseconds),
while reading a saved one takes about a millisecond. Items whose calendar day comes up soonest
go first, so the days you're about to see are ready before the rest.
"""

import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Iterable, Sequence

from . import media
from .models import PreviewItem

# Leave cores free for the gallery's own thumbnail loading and the UI.
DEFAULT_WORKERS = max(1, (os.cpu_count() or 4) // 2)
PROGRESS_INTERVAL = 0.25


@dataclass(frozen=True, slots=True)
class WarmResult:
    total: int      # items checked
    missing: int    # items that needed a preview
    created: int
    failed: int     # unreadable files; remembered, so they aren't retried
    stopped: bool   # cancelled, or the library's folder went away


def days_until(month: int | None, day: int | None, today: date) -> int:
    """How many days until this month and day next come around (0 = today). Unknown dates go last."""
    if not month or not day:
        return 400
    for year in (today.year, today.year + 1):
        try:
            upcoming = date(year, month, day)
        except ValueError:  # February 29 in a year without one: shown on February 28
            upcoming = date(year, month, day - 1)
        if upcoming >= today:
            return (upcoming - today).days
    return 400


def in_preview_order(items: Iterable[PreviewItem], today: date) -> list[PreviewItem]:
    return sorted(items, key=lambda item: days_until(item.month, item.day, today))


def missing_previews(items: Sequence[PreviewItem]) -> list[PreviewItem]:
    """Items with neither a saved preview nor a remembered failure. Lists the cache folder once,
    which is far faster than checking tens of thousands of files one by one."""
    try:
        with os.scandir(media.THUMBNAIL_DIR) as entries:
            names = {entry.name for entry in entries}
    except FileNotFoundError:
        names = set()
    missing = []
    for item in items:
        target = media.thumbnail_cache_path(item.path, item.file_size, item.modified_ns)
        if target.name not in names and target.with_suffix(".failed").name not in names:
            missing.append(item)
    return missing


def warm_thumbnails(items: Sequence[PreviewItem], folder: Path, stop_event: threading.Event,
                    on_progress: Callable[[int, int], None] | None = None,
                    workers: int = DEFAULT_WORKERS) -> WarmResult:
    """Save previews for `items` (in order) that don't have one yet.

    `on_progress(done, missing)` is called from this thread every so often and at the end.
    Stops early if `stop_event` is set or `folder` stops being available (a drive unplugged).
    """
    todo = missing_previews(items)
    created = failed = done = 0
    last_report = 0.0
    stopped = False

    def report(force: bool = False) -> None:
        nonlocal last_report
        now = time.monotonic()
        if on_progress is not None and (force or now - last_report >= PROGRESS_INTERVAL):
            last_report = now
            on_progress(done, len(todo))

    if not todo:
        report(force=True)
        return WarmResult(len(items), 0, 0, 0, stop_event.is_set())

    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="preview-warmer")
    in_flight: set[Future] = set()
    try:
        for item in todo:
            if stop_event.is_set() or (done % 200 == 0 and not folder.is_dir()):
                stopped = True
                break
            in_flight.add(executor.submit(
                media.get_cached_thumbnail, item.path, item.media_type, item.file_size, item.modified_ns))
            if len(in_flight) >= workers * 2:  # keep the queue short, so a stop takes effect quickly
                finished, in_flight = wait(in_flight, return_when=FIRST_COMPLETED)
                for future in finished:
                    done += 1
                    if future.result() is None:
                        failed += 1
                    else:
                        created += 1
                report()
        for future in in_flight:
            done += 1
            if future.result() is None:
                failed += 1
            else:
                created += 1
        in_flight = set()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    report(force=True)
    return WarmResult(len(items), len(todo), created, failed, stopped or stop_event.is_set())
