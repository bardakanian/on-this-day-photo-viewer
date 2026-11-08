"""The library refreshes itself when you come back to the app, but not at launch."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from PySide6.QtWidgets import QApplication, QMessageBox

from onthisday.core import database, media, settings
from onthisday.core.constants import AUTO_RESCAN_SECONDS
from onthisday.core.settings import AppSettings, SettingsStore
from onthisday.ui.main_window import MainWindow

APP = QApplication.instance() or QApplication([])


class WindowTestCase(unittest.TestCase):
    """A main window on a temporary library holding one photo dated today."""

    unplugged_at_launch = False

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        app_dir = root / "app-data"
        self.library = root / "library"
        self.library.mkdir()
        self.add_photo("first.jpg")  # dated by its file time: today
        self.unplugged = self.library.with_name("unplugged")
        if self.unplugged_at_launch:
            self.library.rename(self.unplugged)
        self.patches = [
            patch.object(database, "APP_DIR", app_dir),
            patch.object(database, "DB_FILE", app_dir / "photo_index.sqlite3"),
            patch.object(database, "THUMBNAIL_DIR", app_dir / "thumbnails"),
            patch.object(media, "THUMBNAIL_DIR", app_dir / "thumbnails"),
            patch.object(settings, "APP_DIR", app_dir),
            patch.object(settings, "CONFIG_FILE", app_dir / "config.json"),
            patch.object(settings, "THUMBNAIL_DIR", app_dir / "thumbnails"),
            patch.object(SettingsStore, "load", return_value=AppSettings(self.library)),
            patch.object(media, "parse_macos_metadata_date", return_value=None),
        ]
        for item in self.patches:
            item.start()
        self.errors = []
        self.patches.append(patch.object(QMessageBox, "critical", side_effect=lambda *args: self.errors.append(args)))
        self.patches[-1].start()
        self.window = MainWindow(APP)

    def tearDown(self):
        self.window.close()
        for thread in (self.window.index_thread, self.window.preview_thread):
            if thread:
                thread.join(10)
        # Queries still running would hold the temporary database open, which Windows won't delete.
        self.window.gallery_pool.waitForDone(10000)
        self.window.analytics_pool.waitForDone(10000)
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def add_photo(self, name: str) -> None:
        Image.new("RGB", (16, 12), "teal").save(self.library / name)

    def wait_until(self, condition, timeout: float = 15) -> None:
        end = time.time() + timeout
        while time.time() < end and not condition():
            APP.processEvents()
            time.sleep(0.01)
        self.assertTrue(condition(), "timed out")

    def shown(self) -> set[str]:
        return {record.path.name for record in self.window.gallery.records}


class AutoRefreshTests(WindowTestCase):
    def test_no_scan_at_launch_then_rescan_on_return(self):
        APP.processEvents()  # runs the startup step
        self.assertIsNone(self.window.index_thread)

        self.add_photo("second.jpg")
        self.window.rescan_if_stale()  # back in the app, but it only just opened
        self.assertIsNone(self.window.index_thread)
        self.window.last_scan_finished -= AUTO_RESCAN_SECONDS
        self.window.rescan_if_stale()
        self.wait_until(lambda: self.shown() == {"first.jpg", "second.jpg"})

    def test_unplugged_drive_does_not_interrupt_with_a_dialog(self):
        APP.processEvents()
        self.library.rename(self.unplugged)
        self.window.last_scan_finished -= AUTO_RESCAN_SECONDS
        finished = self.window.last_scan_finished
        self.window.rescan_if_stale()
        self.wait_until(lambda: self.window.last_scan_finished != finished)
        self.assertEqual(self.errors, [])
        self.assertIn("not connected", self.window.status.text())


class UnpluggedAtLaunchTests(WindowTestCase):
    """The library's drive is not connected when the app starts."""

    unplugged_at_launch = True

    def test_library_comes_back_when_the_drive_does(self):
        APP.processEvents()
        self.wait_until(lambda: self.window.gallery.empty.title_label.text() == "Library folder unavailable")
        self.assertEqual(self.window.root_folder, self.library, "the saved folder must not be forgotten")
        self.assertEqual(self.errors, [])
        self.unplugged.rename(self.library)  # plugged back in
        self.window.rescan_if_stale()  # returning to the app; no ten-minute wait
        self.wait_until(lambda: self.shown() == {"first.jpg"})


class SettingsTests(unittest.TestCase):
    def test_missing_folder_is_remembered(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.json"
            config.write_text('{"photo_folder": "/Volumes/Unplugged Drive/Photos"}')
            with patch.object(settings, "CONFIG_FILE", config):
                self.assertEqual(SettingsStore().load().photo_folder, Path("/Volumes/Unplugged Drive/Photos"))


if __name__ == "__main__":
    unittest.main()
