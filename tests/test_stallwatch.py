"""The stall watchdog: it reports a frozen interface thread, with where it was stuck."""

import threading
import time
import unittest

from onthisday.core.stallwatch import StallWatchdog, capture_stack, log_stall, Stall


class WatchdogTests(unittest.TestCase):
    """The test thread plays the interface thread: it beats, or blocks, and the watchdog watches it."""

    def watchdog(self, **options) -> tuple[StallWatchdog, list[Stall]]:
        reports: list[Stall] = []
        options.setdefault("threshold", 0.05)
        options.setdefault("poll", 0.01)
        dog = StallWatchdog(threading.get_ident(), reports.append, **options)
        dog.start()
        self.addCleanup(dog.stop)
        return dog, reports

    def beat_for(self, dog: StallWatchdog, seconds: float, context: str = "") -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            dog.beat(context)
            time.sleep(0.005)

    def test_a_responsive_thread_is_not_reported(self):
        dog, reports = self.watchdog()
        self.beat_for(dog, 0.3)
        self.assertEqual(reports, [])

    def test_a_stall_is_reported_after_it_ends_with_its_duration(self):
        dog, reports = self.watchdog()
        self.beat_for(dog, 0.05)
        time.sleep(0.25)  # the interface thread is stuck
        self.assertEqual(reports, [], "nothing is reported while the thread is still stuck")
        dog.beat()
        self.assertEqual(len(reports), 1)
        self.assertGreaterEqual(reports[0].seconds, 0.2)
        self.assertLess(reports[0].seconds, 2)

    def test_the_report_says_where_the_thread_was_stuck(self):
        dog, reports = self.watchdog()
        self.beat_for(dog, 0.05)
        self.slow_function()
        dog.beat()
        self.assertTrue(any("slow_function" in line for line in reports[0].stack), reports[0].stack)

    def slow_function(self) -> None:
        time.sleep(0.2)

    def test_the_report_carries_what_the_app_was_doing_before_the_stall(self):
        dog, reports = self.watchdog()
        self.beat_for(dog, 0.05, context="page=GalleryPage  scan=idle")
        time.sleep(0.2)
        dog.beat("page=ViewerPage  scan=idle")
        self.assertEqual(reports[0].context, "page=GalleryPage  scan=idle")

    def test_each_stall_is_reported_once(self):
        dog, reports = self.watchdog()
        self.beat_for(dog, 0.03)
        time.sleep(0.25)
        self.beat_for(dog, 0.1)
        self.assertEqual(len(reports), 1)

    def test_the_computer_sleeping_is_not_a_stall(self):
        dog, reports = self.watchdog(max_seconds=0.15)
        self.beat_for(dog, 0.03)
        time.sleep(0.3)
        dog.beat()
        self.assertEqual(reports, [])

    def test_reports_are_capped(self):
        dog, reports = self.watchdog(max_reports=2)
        for _ in range(4):
            self.beat_for(dog, 0.03)
            time.sleep(0.12)
        dog.beat()
        self.assertEqual(len(reports), 2)

    def test_a_failing_report_function_does_not_break_the_beat(self):
        def broken(stall: Stall) -> None:
            raise RuntimeError("log disk full")

        dog = StallWatchdog(threading.get_ident(), broken, threshold=0.05, poll=0.01)
        dog.start()
        self.addCleanup(dog.stop)
        self.beat_for(dog, 0.03)
        time.sleep(0.2)
        with self.assertLogs("onthisday.core.stallwatch", level="ERROR"):
            dog.beat()


class LoggingTests(unittest.TestCase):
    def test_log_line_has_duration_context_and_stack(self):
        stall = Stall(0.62, "page=GalleryPage  scan=idle  previews=saving", ("gallery_grid.py:240 in paintEvent: x",))
        with self.assertLogs("onthisday.core.stallwatch", level="WARNING") as logged:
            log_stall(stall)
        text = logged.output[0]
        for expected in ("UI stalled for 0.62s", "page=GalleryPage", "previews=saving", "paintEvent"):
            self.assertIn(expected, text)

    def test_capture_stack_of_this_thread_names_the_caller(self):
        stack = capture_stack(threading.get_ident())
        self.assertTrue(any("test_capture_stack_of_this_thread_names_the_caller" in line for line in stack))

    def test_capture_stack_of_a_finished_thread_is_empty(self):
        self.assertEqual(capture_stack(-1), ())


if __name__ == "__main__":
    unittest.main()
