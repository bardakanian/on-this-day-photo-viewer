"""Saved previews, and browsing the library while its drive is disconnected."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import tempfile
import threading
import time
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox

from onthisday.core import database, media, settings, thumbnail_warmer
from onthisday.core.database import MediaRepository
from onthisday.core.metadata import MediaMetadata, metadata_rows
from onthisday.core.models import PreviewItem
from onthisday.core.settings import AppSettings, SettingsStore
from onthisday.core.thumbnail_warmer import days_until, in_preview_order, missing_previews, warm_thumbnails
from onthisday.ui.main_window import MainWindow
from onthisday.ui.widgets.gallery_grid import _thumbnail_key

APP = QApplication.instance() or QApplication([])


class IsolatedAppData(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app_dir = self.root / "app-data"
        self.thumbnails = self.app_dir / "thumbnails"
        self.library = self.root / "library"
        self.library.mkdir()
        self.patches = [
            patch.object(database, "APP_DIR", self.app_dir),
            patch.object(database, "DB_FILE", self.app_dir / "photo_index.sqlite3"),
            patch.object(database, "THUMBNAIL_DIR", self.thumbnails),
            patch.object(media, "THUMBNAIL_DIR", self.thumbnails),
            patch.object(settings, "APP_DIR", self.app_dir),
            patch.object(settings, "CONFIG_FILE", self.app_dir / "config.json"),
            patch.object(settings, "THUMBNAIL_DIR", self.thumbnails),
            patch.object(media, "parse_macos_metadata_date", return_value=None),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def photo(self, name: str, size=(64, 48)) -> PreviewItem:
        path = self.library / name
        Image.new("RGB", size, "orange").save(path)
        stat = path.stat()
        return PreviewItem(path, "image", stat.st_size, stat.st_mtime_ns, 5, 1)


class PreviewOrderTests(unittest.TestCase):
    def test_days_until(self):
        today = date(2026, 11, 4)
        self.assertEqual(days_until(11, 4, today), 0)
        self.assertEqual(days_until(11, 5, today), 1)
        self.assertEqual(days_until(11, 3, today), 364)  # just passed: next year
        self.assertEqual(days_until(None, None, today), 400)
        # 2027 has no February 29, so leap-day items come up with February 28.
        self.assertEqual(days_until(2, 29, date(2027, 2, 28)), 0)

    def test_soonest_days_first(self):
        item = lambda month, day: PreviewItem(Path(f"/{month}-{day}"), "image", 1, 1, month, day)
        ordered = in_preview_order([item(1, 1), item(None, None), item(11, 5), item(11, 4)], date(2026, 11, 4))
        self.assertEqual([(i.month, i.day) for i in ordered], [(11, 4), (11, 5), (1, 1), (None, None)])


class WarmerTests(IsolatedAppData):
    def test_saves_missing_previews_once(self):
        items = [self.photo(f"{index}.jpg") for index in range(5)]
        broken = self.library / "broken.jpg"
        broken.write_bytes(b"not an image")
        items.append(PreviewItem(broken, "image", 12, broken.stat().st_mtime_ns, 5, 1))
        progress = []
        result = warm_thumbnails(items, self.library, threading.Event(), lambda done, missing: progress.append((done, missing)), workers=2)
        self.assertEqual((result.missing, result.created, result.failed, result.stopped), (6, 5, 1, False))
        self.assertEqual(progress[-1], (6, 6))
        self.assertEqual(missing_previews(items), [], "made and failed items are both remembered")
        again = warm_thumbnails(items, self.library, threading.Event())
        self.assertEqual((again.missing, again.created), (0, 0))

    def test_stops_when_asked_or_when_the_drive_goes(self):
        items = [self.photo(f"{index}.jpg") for index in range(3)]
        stop = threading.Event()
        stop.set()
        self.assertTrue(warm_thumbnails(items, self.library, stop).stopped)
        gone = self.root / "unplugged"
        self.assertTrue(warm_thumbnails(items, gone, threading.Event()).stopped)
        self.assertEqual(len(missing_previews(items)), 3)


class OfflineQueryTests(IsolatedAppData):
    def test_index_lists_missing_files_only_when_asked(self):
        photo = self.photo("taken.jpg")
        connection = database.open_database()
        connection.execute(
            "INSERT INTO photos (folder_root, file_path, file_size, modified_ns, capture_ts, capture_year,"
            " capture_month, capture_day, media_type) VALUES (?, ?, ?, ?, '2020-05-01T10:00:00', 2020, 5, 1, 'image')",
            (str(self.library.resolve()), str(photo.path.resolve()), photo.file_size, photo.modified_ns),
        )
        connection.commit()
        connection.close()
        repository = MediaRepository()
        self.assertEqual(len(repository.preview_items(self.library)), 1)
        photo.path.unlink()
        self.assertEqual(repository.matches_for_date(self.library, date(2026, 5, 1), "All"), [])
        offline = repository.matches_for_date(self.library, date(2026, 5, 1), "All", check_files=False)
        self.assertEqual([record.path.name for record in offline], ["taken.jpg"])

    def test_save_previews_setting(self):
        store = SettingsStore()
        self.assertTrue(store.load().save_previews)  # on unless turned off
        store.save(AppSettings(self.library, "dark", save_previews=False))
        self.assertFalse(store.load().save_previews)
        self.assertEqual(json.loads((self.app_dir / "config.json").read_text())["photo_folder"], str(self.library))

    def test_info_panel_falls_back_to_the_indexed_date(self):
        unreadable = MediaMetadata(Path("/Volumes/Gone/a.jpg"), "image", None, None, None, None, None)
        rows = dict(metadata_rows(unreadable, datetime(2019, 5, 1, 9, 30)))
        self.assertEqual(rows["Date taken"], "May 1, 2019  •  09:30")
        self.assertEqual(rows["Date from"], "Library index (file not available)")


class UnpluggedBrowsingTests(IsolatedAppData):
    """End to end: scan, save previews, unplug the drive, then browse."""

    def setUp(self):
        super().setUp()
        Image.new("RGB", (800, 600), "orange").save(self.library / "today.jpg")  # dated by file time: today
        self.patches.append(patch.object(SettingsStore, "load", return_value=AppSettings(self.library)))
        self.patches.append(patch.object(QMessageBox, "critical"))
        for item in self.patches[-2:]:
            item.start()
        self.window = MainWindow(APP)

    def tearDown(self):
        self.window.close()
        for thread in (self.window.index_thread, self.window.preview_thread):
            if thread:
                thread.join(10)
        # Queries still running would hold the temporary database open, which Windows won't delete.
        self.window.gallery_pool.waitForDone(10000)
        self.window.analytics_pool.waitForDone(10000)
        super().tearDown()

    def wait_until(self, condition, timeout: float = 15) -> None:
        end = time.time() + timeout
        while time.time() < end and not condition():
            APP.processEvents()
            time.sleep(0.01)
        self.assertTrue(condition(), "timed out")

    def test_gallery_and_viewer_use_saved_previews(self):
        APP.processEvents()
        self.window.start_indexing()
        self.wait_until(lambda: len(self.window.gallery.records) == 1)
        record = self.window.gallery.records[0]
        saved = media.thumbnail_cache_path(record.path, record.file_size, record.modified_ns)
        self.wait_until(saved.exists)  # made by the background preview saver after the scan
        self.wait_until(lambda: not self.window.preview_thread.is_alive())

        self.library.rename(self.root / "unplugged")
        self.window.refresh_gallery()
        self.wait_until(lambda: self.window.gallery.grid.offline)
        gallery = self.window.gallery
        self.assertEqual([r.path.name for r in gallery.records], ["today.jpg"])
        self.assertIn("not connected", gallery.summary.text())
        self.window.resize(1200, 800)
        self.window.show()  # the grid loads previews for the cards it draws
        self.wait_until(lambda: isinstance(gallery.grid._pixmaps.get(_thumbnail_key(record)), QPixmap))

        self.window._open_from_gallery(record)
        viewer = self.window.viewer
        self.assertFalse(viewer.trash_button.isEnabled())
        self.wait_until(lambda: "saved preview" in viewer.subtitle.text())
        self.assertTrue(viewer.canvas.has_image, "the saved preview stays on screen")
        self.window.close()


if __name__ == "__main__":
    unittest.main()
