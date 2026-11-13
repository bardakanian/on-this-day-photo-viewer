"""Time-left estimates for scans and saving previews."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from onthisday.core.progress import Eta, format_duration_words, time_left_text
from onthisday.core.settings import AppSettings, SettingsStore
from onthisday.core.thumbnail_warmer import WarmResult
from onthisday.ui.main_window import MainWindow

APP = QApplication.instance() or QApplication([])


class EtaTests(unittest.TestCase):
    def test_steady_rate(self):
        eta = Eta(now=0)
        for second in range(1, 11):
            left = eta.remaining(second * 100, 10_000, now=second)
        self.assertAlmostEqual(left, 90, delta=1)  # 9,000 left at 100 a second

    def test_no_guess_too_early(self):
        eta = Eta(now=0)
        self.assertIsNone(eta.remaining(50, 10_000, now=1))  # under 3 seconds in
        self.assertIsNone(Eta(now=0).remaining(10, 10_000, now=10))  # under 1% done

    def test_follows_a_slowdown_without_jumping(self):
        eta = Eta(now=0)
        for second in range(1, 11):
            eta.remaining(second * 100, 10_000, now=second)
        left = eta.remaining(1_010, 10_000, now=11)  # one slow second: 10 instead of 100
        self.assertGreater(left, 90)
        self.assertLess(left, 900, "one slow second shouldn't swing the estimate all the way")

    def test_finished(self):
        self.assertEqual(Eta(now=0).remaining(5, 5, now=1), 0.0)

    def test_wording(self):
        self.assertEqual(format_duration_words(0.4), "1 s")
        self.assertEqual(format_duration_words(45), "45 s")
        self.assertEqual(format_duration_words(200), "3 min")
        self.assertEqual(format_duration_words(4_800), "1 h 20 min")
        self.assertEqual(format_duration_words(7_200), "2 h")
        self.assertEqual(time_left_text(None), "estimating time left…")
        self.assertEqual(time_left_text(2), "almost done")
        self.assertEqual(time_left_text(200), "about 3 min left")


class StatusTests(unittest.TestCase):
    def setUp(self):
        with patch.object(SettingsStore, "load", return_value=AppSettings()):
            self.window = MainWindow(APP)

    def tearDown(self):
        self.window.close()

    def test_scan_shows_position_time_left_and_finish(self):
        window = self.window
        window.active_scan_id = 1
        with patch("onthisday.core.progress.time.monotonic", return_value=100.0):
            window._handle_index_event({"type": "scan_started", "scan_id": 1, "expected": 10_000})
        self.assertEqual((window.progress.maximum(), window.progress.isHidden()), (10_000, False))
        for second in range(1, 11):
            with patch("onthisday.core.progress.time.monotonic", return_value=100.0 + second):
                window._handle_index_event({"type": "scan_progress", "scan_id": 1, "scanned": second * 500,
                                            "updated": 0, "unchanged": second * 500, "errors": 0})
        self.assertIn("5,000 of about 10,000 checked", window.status.text())
        self.assertIn("about 10 s left", window.status.text())
        with patch("onthisday.core.progress.time.monotonic", return_value=120.0):
            window._handle_index_event({"type": "scan_progress", "scan_id": 1, "scanned": 10_000,
                                        "updated": 0, "unchanged": 10_000, "errors": 0})
        self.assertIn("10,000 of about 10,000 checked", window.status.text())
        with patch("onthisday.core.progress.time.monotonic", return_value=121.0):
            window._handle_index_event({"type": "scan_progress", "scan_id": 1, "scanned": 10_050,
                                        "updated": 50, "unchanged": 10_000, "errors": 0})
        self.assertIn("more files than last time", window.status.text())
        with patch("onthisday.core.progress.time.monotonic", return_value=190.0), \
                patch.object(window, "start_saving_previews"), \
                patch("onthisday.ui.main_window.notify") as notify:
            window._handle_index_event({"type": "scan_complete", "scan_id": 1, "scanned": 10_000, "updated": 0,
                                        "unchanged": 10_000, "deleted": 0, "errors": 0,
                                        "total_indexed": 10_000, "total_videos": 0})
        self.assertIn("scan finished in 2 min", window.status.text())
        notify.assert_called_once_with("Scan finished", "10,000 items checked in 2 min  ·  0 new or changed, 0 removed")
        self.assertTrue(window.progress.isHidden())

    def test_first_scan_says_the_total_is_unknown(self):
        window = self.window
        window.active_scan_id = 1
        window._handle_index_event({"type": "scan_started", "scan_id": 1, "expected": 0})
        window._handle_index_event({"type": "scan_progress", "scan_id": 1, "scanned": 50,
                                    "updated": 50, "unchanged": 0, "errors": 0})
        self.assertIn("isn't known yet", window.status.text())
        self.assertEqual(window.progress.maximum(), 0)  # a moving bar, not a filling one

    def test_previews_show_time_left_and_finish(self):
        window = self.window
        window.ready_text = "Library ready"
        stop = window.preview_stop
        with patch("onthisday.core.progress.time.monotonic", return_value=0.0):
            window.preview_eta = type(window.preview_eta)()
        for second in range(1, 11):
            with patch("onthisday.core.progress.time.monotonic", return_value=float(second)):
                window._handle_preview_event({"stop": stop, "done": second * 10, "missing": 1_000})
        self.assertIn("saving previews 100 of 1,000", window.status.text())
        self.assertIn("about 2 min left", window.status.text())  # 900 left at 10 a second: 90 s
        with patch("onthisday.core.progress.time.monotonic", return_value=100.0), \
                patch("onthisday.ui.main_window.notify") as notify:
            window._handle_preview_event({"stop": stop, "result": WarmResult(1_000, 1_000, 990, 10, False)})
        self.assertEqual(notify.call_args.args[0], "Previews saved")
        self.assertEqual(window.status.text(), "Library ready  ·  all previews saved (990 new, in 2 min)")


    def test_short_jobs_finish_quietly(self):
        window = self.window
        window.active_scan_id = 1
        window._handle_index_event({"type": "scan_started", "scan_id": 1, "expected": 10})
        with patch.object(window, "start_saving_previews"), patch("onthisday.ui.main_window.notify") as notify:
            window._handle_index_event({"type": "scan_complete", "scan_id": 1, "scanned": 10, "updated": 0,
                                        "unchanged": 10, "deleted": 0, "errors": 0,
                                        "total_indexed": 10, "total_videos": 0})
        notify.assert_not_called()


class NotificationTests(unittest.TestCase):
    def test_quotes_are_escaped_for_applescript(self):
        from onthisday.ui import notifications
        with patch.object(notifications.sys, "platform", "darwin"), \
                patch.object(notifications.subprocess, "Popen") as popen:
            notifications.notify('Scan "done"', "C:\\photos")
        script = popen.call_args.args[0][2]
        self.assertEqual(script, 'display notification "C:\\\\photos" with title "Scan \\"done\\""')


if __name__ == "__main__":
    unittest.main()
