"""Seeing and freeing the space saved previews take."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox

from onthisday.core import database, indexer, media, preview_cache
from onthisday.core.indexer import MediaIndexer
from onthisday.core.preview_cache import CacheUsage, cache_usage, delete_previews
from onthisday.ui.dialogs import PreferencesDialog
from tests.test_auto_refresh import WindowTestCase

APP = QApplication.instance() or QApplication([])


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.thumbnails = Path(self.temp.name) / "thumbnails"
        self.patch = patch.object(media, "THUMBNAIL_DIR", self.thumbnails)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def fill(self) -> None:
        self.thumbnails.mkdir()
        (self.thumbnails / "a.jpg").write_bytes(b"x" * 300)
        (self.thumbnails / "b.jpg").write_bytes(b"x" * 200)
        (self.thumbnails / "c.failed").write_bytes(b"")
        (self.thumbnails / "d.123-4.part").write_bytes(b"x" * 10)
        (self.thumbnails / "notes.txt").write_bytes(b"x" * 1000)  # not ours: never counted or deleted

    def test_usage_counts_only_cache_files(self):
        self.fill()
        self.assertEqual(cache_usage(), CacheUsage(510, 4))

    def test_missing_folder_is_empty(self):
        self.assertEqual(cache_usage(), CacheUsage(0, 0))
        self.assertEqual(delete_previews(), CacheUsage(0, 0))

    def test_delete_removes_cache_files_and_reports_what_was_freed(self):
        self.fill()
        self.assertEqual(delete_previews(), CacheUsage(510, 4))
        self.assertEqual(sorted(path.name for path in self.thumbnails.iterdir()), ["notes.txt"])

    def test_stopped_delete_leaves_the_rest(self):
        self.fill()
        stop = threading.Event()
        stop.set()
        self.assertEqual(delete_previews(stop), CacheUsage(0, 0))
        self.assertEqual(cache_usage().files, 4)


class ClipPreviewPruneTests(unittest.TestCase):
    """A scan deletes the previews of Live Photo clips, which are never shown on their own."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        app_dir = root / "app-data"
        self.patches = [
            patch.object(database, "APP_DIR", app_dir),
            patch.object(database, "DB_FILE", app_dir / "photo_index.sqlite3"),
            patch.object(database, "THUMBNAIL_DIR", app_dir / "thumbnails"),
            patch.object(media, "THUMBNAIL_DIR", app_dir / "thumbnails"),
            patch.object(indexer, "HEIC_ENABLED", True),
            patch.object(indexer, "get_capture_date", side_effect=lambda path, _type: {
                "IMG_1.HEIC": datetime(2023, 5, 14, 10, 0, 0),
                "IMG_1.MOV": datetime(2023, 5, 14, 10, 0, 1),
            }[path.name]),
        ]
        for item in self.patches:
            item.start()
        self.library = root / "library"
        self.library.mkdir()
        for name in ("IMG_1.HEIC", "IMG_1.MOV"):
            (self.library / name).write_bytes(b"x")

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def preview_of(self, name: str) -> Path:
        path = (self.library / name).resolve()
        stat = path.stat()
        return media.thumbnail_cache_path(path, stat.st_size, stat.st_mtime_ns)

    def test_scan_prunes_the_clip_preview_and_keeps_the_photo_preview(self):
        MediaIndexer(self.library, threading.Event(), 1, lambda event: None).run()
        photo, clip = self.preview_of("IMG_1.HEIC"), self.preview_of("IMG_1.MOV")
        for preview in (photo, clip):
            preview.write_bytes(b"jpeg")
        MediaIndexer(self.library, threading.Event(), 2, lambda event: None).run()
        self.assertTrue(photo.exists())
        self.assertFalse(clip.exists())


class DialogTests(unittest.TestCase):
    def test_cache_line_and_button(self):
        dialog = PreferencesDialog("system")
        self.assertIn("counting", dialog.cache_label.text())
        self.assertFalse(dialog.delete_previews.isEnabled())
        dialog.set_cache_usage(CacheUsage(4_200_000_000, 119_530))
        self.assertEqual(dialog.cache_label.text(), "Saved previews: 4.2 GB (119,530 files)")
        self.assertTrue(dialog.delete_previews.isEnabled())
        dialog.set_cache_usage(None, deleting=True)
        self.assertIn("deleting", dialog.cache_label.text())
        self.assertFalse(dialog.delete_previews.isEnabled())
        dialog.set_cache_usage(CacheUsage(0, 0))
        self.assertEqual(dialog.cache_label.text(), "Saved previews: none")
        self.assertFalse(dialog.delete_previews.isEnabled())
        dialog.deleteLater()


class WindowDeleteTests(WindowTestCase):
    def tearDown(self):
        if self.window.cache_job:
            self.window.cache_job.join(10)
        super().tearDown()

    def wait_for_previews(self) -> None:
        APP.processEvents()  # the startup step
        self.window.start_indexing()  # a scan saves previews when it finishes
        self.wait_until(lambda: cache_usage().files > 0)
        self.wait_until(lambda: not self.window.scan_running() and not self.window.saving_previews())

    def count(self) -> CacheUsage:
        self.window.cache_usage = None
        self.window._start_cache_job(count_only=True)
        self.wait_until(lambda: self.window.cache_usage is not None)
        return self.window.cache_usage

    def test_deleted_previews_are_saved_again_while_saving_is_on(self):
        self.wait_for_previews()
        self.assertEqual(self.count().files, 1)
        self.window._delete_previews()
        self.wait_until(lambda: "freed" in self.window.status.text())
        # Saving previews is on, so the saver remakes what was deleted.
        self.wait_until(lambda: cache_usage().files == 1)

    def test_turning_previews_off_offers_to_delete_them(self):
        self.wait_for_previews()
        self.count()
        self.window.settings.save_previews = False

        def pick_delete(box):
            return next(button for button in box.buttons() if button.text() == "Delete Previews")

        with patch.object(QMessageBox, "exec", lambda box: 0), patch.object(QMessageBox, "clickedButton", pick_delete):
            self.window._offer_to_delete_previews()
        self.wait_until(lambda: "freed" in self.window.status.text())
        self.window.cache_job.join(10)
        APP.processEvents()
        self.assertEqual(cache_usage().files, 0)
        self.assertFalse(self.window.saving_previews())

    def test_keeping_them_deletes_nothing(self):
        self.wait_for_previews()
        self.count()

        def pick_keep(box):
            return next(button for button in box.buttons() if button.text() == "Keep Them")

        with patch.object(QMessageBox, "exec", lambda box: 0), patch.object(QMessageBox, "clickedButton", pick_keep):
            self.window._offer_to_delete_previews()
        self.assertFalse(self.window.deleting_previews())
        self.assertEqual(cache_usage().files, 1)


if __name__ == "__main__":
    unittest.main()


class CacheEventRegressionTests(WindowTestCase):
    def test_closing_window_does_not_restart_saving(self):
        stop = threading.Event()
        stop.set()  # closeEvent sets it
        with patch.object(self.window, "start_saving_previews") as start:
            self.window._handle_cache_event({"stop": stop, "freed": CacheUsage(10, 1)})
        start.assert_not_called()

    def test_deleted_while_settings_open_saves_again_when_it_closes(self):
        class StillCounting:  # the delete job's final recount hasn't finished when Settings closes
            def is_alive(self):
                return True

        def exec_dialog(dialog):
            self.window._handle_cache_event({"stop": threading.Event(), "freed": CacheUsage(10, 1)})
            self.window.cache_job, self.window.cache_job_deletes = StillCounting(), True
            return 0

        with patch.object(PreferencesDialog, "exec", exec_dialog), \
                patch.object(self.window, "_start_cache_job"), \
                patch.object(self.window, "start_saving_previews") as start:
            self.window.show_preferences()
        start.assert_called_once()
        self.window.cache_job = None


class UpgradeRaceTests(unittest.TestCase):
    """Several threads opening an index from before Live Photos at once must not fail."""

    def test_concurrent_first_opens(self):
        with tempfile.TemporaryDirectory() as temp:
            app_dir = Path(temp)
            with patch.object(database, "APP_DIR", app_dir), \
                    patch.object(database, "DB_FILE", app_dir / "index.sqlite3"), \
                    patch.object(database, "THUMBNAIL_DIR", app_dir / "thumbnails"):
                for attempt in range(10):
                    (app_dir / "index.sqlite3").unlink(missing_ok=True)
                    connection = database.sqlite3.connect(app_dir / "index.sqlite3")
                    connection.execute("""
                        CREATE TABLE photos (folder_root TEXT NOT NULL, file_path TEXT NOT NULL,
                            file_size INTEGER NOT NULL, modified_ns INTEGER NOT NULL, capture_ts TEXT,
                            capture_year INTEGER, capture_month INTEGER, capture_day INTEGER,
                            media_type TEXT DEFAULT 'image', video_metadata_version INTEGER DEFAULT 0,
                            PRIMARY KEY (folder_root, file_path))
                    """)
                    connection.commit()
                    connection.close()
                    barrier, errors = threading.Barrier(6), []

                    def open_it():
                        barrier.wait()
                        try:
                            database.open_database().close()
                        except Exception as error:
                            errors.append(error)

                    threads = [threading.Thread(target=open_it) for _ in range(6)]
                    for thread in threads:
                        thread.start()
                    for thread in threads:
                        thread.join()
                    self.assertEqual(errors, [], f"attempt {attempt}")
