"""The 12-hour / 24-hour clock setting, and everywhere it shows up."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from onthisday.core import settings
from onthisday.core.metadata import MediaMetadata, metadata_rows
from onthisday.core.models import VideoRecord, ViewerItem
from onthisday.core.settings import SettingsStore
from onthisday.core.timeformat import TIME_12_HOUR, TIME_24_HOUR, format_capture, format_time
from onthisday.ui.dialogs import PreferencesDialog
from onthisday.ui.pages.videos_page import VideosPage
from onthisday.ui.pages.viewer_page import ViewerPage

APP = QApplication.instance() or QApplication([])


class FormatTests(unittest.TestCase):
    def test_12_hour_clock(self):
        for hour, minute, expected in ((0, 5, "12:05 AM"), (9, 5, "9:05 AM"), (12, 0, "12:00 PM"), (23, 59, "11:59 PM")):
            self.assertEqual(format_time(datetime(2020, 1, 1, hour, minute), TIME_12_HOUR), expected)

    def test_24_hour_clock(self):
        self.assertEqual(format_time(datetime(2020, 1, 1, 9, 5), TIME_24_HOUR), "09:05")
        self.assertEqual(format_time(datetime(2020, 1, 1, 14, 5, 7), TIME_24_HOUR, seconds=True), "14:05:07")

    def test_seconds_on_12_hour_clock(self):
        self.assertEqual(format_time(datetime(2020, 1, 1, 14, 5, 7), TIME_12_HOUR, seconds=True), "2:05:07 PM")

    def test_full_capture_text(self):
        value = datetime(2015, 7, 4, 14, 5)
        self.assertEqual(format_capture(value), "July 4, 2015  •  2:05 PM")
        self.assertEqual(format_capture(value, TIME_24_HOUR), "July 4, 2015  •  14:05")

    def test_info_panel_rows_follow_the_setting(self):
        info = MediaMetadata(Path("a.jpg"), "image", None, None, None, datetime(2015, 7, 4, 14, 5), None)
        self.assertEqual(dict(metadata_rows(info, TIME_24_HOUR))["Date taken"], "July 4, 2015  •  14:05")


class SettingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.app_dir = Path(temp.name)
        self.config = self.app_dir / "config.json"
        for name, value in (("APP_DIR", self.app_dir), ("CONFIG_FILE", self.config),
                            ("THUMBNAIL_DIR", self.app_dir / "thumbnails")):
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_defaults_to_12_hour_for_existing_configs(self):
        self.config.write_text(json.dumps({"theme": "dark"}))
        self.assertEqual(SettingsStore().load().time_format, TIME_12_HOUR)

    def test_choice_is_remembered(self):
        store = SettingsStore()
        loaded = store.load()
        loaded.time_format = TIME_24_HOUR
        store.save(loaded)
        self.assertEqual(store.load().time_format, TIME_24_HOUR)

    def test_unknown_value_falls_back(self):
        self.config.write_text(json.dumps({"time_format": "sundial"}))
        self.assertEqual(SettingsStore().load().time_format, TIME_12_HOUR)


class InterfaceTests(unittest.TestCase):
    def test_dialog_shows_and_returns_the_choice(self):
        dialog = PreferencesDialog("system", TIME_24_HOUR)
        self.assertEqual(dialog.selected_time_format, TIME_24_HOUR)
        dialog.time_format.setCurrentIndex(dialog.time_format.findData(TIME_12_HOUR))
        self.assertEqual(dialog.selected_time_format, TIME_12_HOUR)

    def test_viewer_updates_the_open_item(self):
        viewer = ViewerPage()
        self.addCleanup(viewer.shutdown)
        item = ViewerItem(Path("a.jpg"), datetime(2015, 7, 4, 14, 5), "image", 1, 1)
        viewer.items = [item]
        viewer.set_time_format(TIME_12_HOUR)
        self.assertEqual(viewer.subtitle.text(), "July 4, 2015  •  2:05 PM")
        viewer.set_time_format(TIME_24_HOUR)
        self.assertEqual(viewer.subtitle.text(), "July 4, 2015  •  14:05")

    def test_video_library_sorts_by_real_time_not_text(self):
        page = VideosPage()
        page.set_records([
            VideoRecord(Path("morning.mov"), "2020-01-01T10:00:00", 1, 1),
            VideoRecord(Path("early.mov"), "2020-01-01T02:00:00", 1, 1),
            VideoRecord(Path("evening.mov"), "2020-01-01T13:00:00", 1, 1),
        ])
        page.proxy.sort(2, Qt.SortOrder.AscendingOrder)
        names = [page.proxy.index(row, 0).data() for row in range(3)]
        self.assertEqual(names, ["early.mov", "morning.mov", "evening.mov"])
        self.assertEqual(page.proxy.index(0, 2).data(), "2020-01-01  2:00:00 AM")
        page.set_time_format(TIME_24_HOUR)
        self.assertEqual(page.proxy.index(2, 2).data(), "2020-01-01  13:00:00")


if __name__ == "__main__":
    unittest.main()
