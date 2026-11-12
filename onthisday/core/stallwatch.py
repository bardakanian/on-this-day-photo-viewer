"""Notice when the window stops responding, and write down what it was busy with.

The interface thread calls `beat()` every few milliseconds, from a timer in its own event loop.
A watchdog thread checks that heartbeat. When it goes quiet for longer than the threshold, the
interface thread is stuck in something slow, so the watchdog snapshots that thread's stack. The
stall is reported once the interface thread is back, with how long it lasted. Python code is
what shows in the stack; a stack that ends in the entry script means the time went into Qt itself
(painting, layout or style work).
"""

import logging
import os
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Callable

from .constants import MAX_STALL_REPORTS, MAX_STALL_SECONDS, STALL_THRESHOLD_SECONDS

LOGGER = logging.getLogger(__name__)

STACK_DEPTH = 10  # innermost frames kept per stall


@dataclass(frozen=True, slots=True)
class Stall:
    seconds: float
    context: str              # what the app was doing at the last heartbeat before the stall
    stack: tuple[str, ...]    # where the interface thread was, outermost call first


def log_stall(stall: Stall) -> None:
    where = "\n".join(f"    {line}" for line in stall.stack) or "    (stack unavailable)"
    LOGGER.warning("UI stalled for %.2fs  ·  %s\n%s", stall.seconds, stall.context or "no context", where)


def capture_stack(thread_id: int) -> tuple[str, ...]:
    frame = sys._current_frames().get(thread_id)
    if frame is None:
        return ()
    entries = traceback.extract_stack(frame, limit=STACK_DEPTH)
    return tuple(
        f"{os.path.basename(entry.filename)}:{entry.lineno} in {entry.name}" + (f": {entry.line}" if entry.line else "")
        for entry in entries
    )


class StallWatchdog:
    def __init__(self, thread_id: int, report: Callable[[Stall], None] = log_stall,
                 threshold: float = STALL_THRESHOLD_SECONDS, poll: float = 0.05,
                 max_reports: int = MAX_STALL_REPORTS, max_seconds: float = MAX_STALL_SECONDS,
                 clock: Callable[[], float] = time.monotonic):
        self._thread_id = thread_id
        self._report = report
        self._threshold = threshold
        self._poll = poll
        self._max_reports = max_reports
        self._max_seconds = max_seconds  # longer gaps are the computer sleeping, not the app stalling
        self._clock = clock
        self._lock = threading.Lock()
        self._last_beat = clock()
        self._context = ""
        self._open: tuple[float, str, tuple[str, ...]] | None = None  # start, context, stack
        self._reported = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        with self._lock:
            self._last_beat = self._clock()
        self._thread = threading.Thread(target=self._watch, daemon=True, name="stall-watchdog")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def beat(self, context: str = "") -> None:
        """Called by the interface thread; `context` describes what the app is doing right now."""
        now = self._clock()
        with self._lock:
            opened, self._open = self._open, None
            self._last_beat = now
            self._context = context
        if opened is not None:
            self._finish(opened, now)

    def _watch(self) -> None:
        while not self._stop.wait(self._poll):
            now = self._clock()
            with self._lock:
                if self._open is None and now - self._last_beat >= self._threshold:
                    self._open = (self._last_beat, self._context, capture_stack(self._thread_id))

    def _finish(self, opened: tuple[float, str, tuple[str, ...]], now: float) -> None:
        started, context, stack = opened
        seconds = now - started
        if seconds > self._max_seconds or self._reported > self._max_reports:
            return
        self._reported += 1
        if self._reported > self._max_reports:
            LOGGER.warning("More than %d UI stalls this session; not logging any further ones", self._max_reports)
            return
        try:
            self._report(Stall(seconds, context, stack))
        except Exception:
            LOGGER.exception("Could not report a UI stall")
