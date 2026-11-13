"""Time-left estimates for long background jobs (scans, saving previews). Kept free of Qt so it can be tested."""

import time

# Too early, the rate is mostly start-up cost and the estimate jumps around; show none until then.
MIN_SECONDS = 3.0
MIN_FRACTION = 0.01
# How strongly the newest rate counts. Lower is steadier; higher follows speed changes faster.
SMOOTHING = 0.2


class Eta:
    """Estimates the time left from how fast `done` has been growing, smoothed so it doesn't jump."""

    def __init__(self, now: float | None = None):
        self.started = time.monotonic() if now is None else now
        self._last_time = self.started
        self._last_done = 0
        self._rate: float | None = None  # items per second

    def elapsed(self, now: float | None = None) -> float:
        return (time.monotonic() if now is None else now) - self.started

    def remaining(self, done: int, total: int, now: float | None = None) -> float | None:
        """Seconds left, or None while there isn't enough to go on yet."""
        now = time.monotonic() if now is None else now
        if done > self._last_done and now > self._last_time:
            rate = (done - self._last_done) / (now - self._last_time)
            self._rate = rate if self._rate is None else SMOOTHING * rate + (1 - SMOOTHING) * self._rate
            self._last_time, self._last_done = now, done
        if total <= 0 or done >= total:
            return 0.0 if total > 0 else None
        if not self._rate or now - self.started < MIN_SECONDS or done < total * MIN_FRACTION:
            return None
        return (total - done) / self._rate


def format_duration_words(seconds: float) -> str:
    """A rounded duration for people: "45 s", "3 min", "1 h 20 min"."""
    seconds = max(0, round(seconds))
    if seconds < 60:
        return f"{max(1, seconds)} s"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"


def time_left_text(seconds: float | None) -> str:
    if seconds is None:
        return "estimating time left…"
    if seconds < 5:
        return "almost done"
    return f"about {format_duration_words(seconds)} left"
