"""Live Photos: a still and its motion clip are paired in the index and shown as one item."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import tempfile
import threading
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from onthisday.core import database, indexer, media, settings
from onthisday.core.indexer import MediaIndexer
from onthisday.core.live_photos import PairingRow, pair_live_photos, repair_live_photos
from onthisday.core.models import ViewerItem
from onthisday.ui.pages.viewer_page import ViewerPage

APP = QApplication.instance() or QApplication([])

INSERT_ROW = """
    INSERT INTO photos (folder_root, file_path, file_size, modified_ns, capture_ts, capture_year,
                        capture_month, capture_day, media_type, video_metadata_version)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def row(path: str, media_type: str, stamp: str | None) -> PairingRow:
    return PairingRow(path, media_type, datetime.fromisoformat(stamp) if stamp else None)


class PairingTests(unittest.TestCase):
    def test_same_name_same_folder_close_in_time_pairs(self):
        pairs = pair_live_photos([
            row("/a/IMG_4330.HEIC", "image", "2023-05-14T10:00:00"),
            row("/a/IMG_4330.MOV", "video", "2023-05-14T10:00:02"),
        ])
        self.assertEqual(pairs, [("/a/IMG_4330.HEIC", "/a/IMG_4330.MOV")])

    def test_name_match_ignores_case(self):
        pairs = pair_live_photos([
            row("/a/img_1.jpg", "image", "2023-05-14T10:00:00"),
            row("/a/IMG_1.mov", "video", "2023-05-14T10:00:00"),
        ])
        self.assertEqual(len(pairs), 1)

    def test_files_that_only_share_a_name_stay_apart(self):
        cases = [
            # Different folders.
            [row("/a/IMG_1.HEIC", "image", "2023-05-14T10:00:00"), row("/b/IMG_1.MOV", "video", "2023-05-14T10:00:00")],
            # Taken minutes apart: a camera reused the number.
            [row("/a/IMG_1.JPG", "image", "2023-05-14T10:00:00"), row("/a/IMG_1.MOV", "video", "2023-05-14T10:05:00")],
            # One of them has no date to compare.
            [row("/a/IMG_1.JPG", "image", None), row("/a/IMG_1.MOV", "video", "2023-05-14T10:00:00")],
            # Two photos and a video with one name: ambiguous.
            [row("/a/IMG_1.JPG", "image", "2023-05-14T10:00:00"), row("/a/IMG_1.HEIC", "image", "2023-05-14T10:00:00"),
             row("/a/IMG_1.MOV", "video", "2023-05-14T10:00:00")],
            # Two photos, no video.
            [row("/a/IMG_1.JPG", "image", "2023-05-14T10:00:00"), row("/a/IMG_1.PNG", "image", "2023-05-14T10:00:00")],
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                self.assertEqual(pair_live_photos(rows), [])


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.app_dir = self.root / "app-data"
        self.patches = [
            patch.object(database, "APP_DIR", self.app_dir),
            patch.object(database, "DB_FILE", self.app_dir / "photo_index.sqlite3"),
            patch.object(database, "THUMBNAIL_DIR", self.app_dir / "thumbnails"),
            patch.object(media, "THUMBNAIL_DIR", self.app_dir / "thumbnails"),
            patch.object(settings, "APP_DIR", self.app_dir),
        ]
        for item in self.patches:
            item.start()
        self.library = self.root / "library"
        self.library.mkdir()
        self.photo = self.library / "IMG_4330.HEIC"
        self.clip = self.library / "IMG_4330.MOV"
        self.video = self.library / "Birthday.mov"
        for path in (self.photo, self.clip, self.video):
            path.touch()
        self.repository = database.MediaRepository()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def insert_rows(self) -> None:
        folder_root = str(self.library.resolve())
        connection = database.open_database()
        connection.executemany(INSERT_ROW, [
            (folder_root, str(self.photo.resolve()), 1, 1, "2023-05-14T10:00:00", 2023, 5, 14, "image", 9),
            (folder_root, str(self.clip.resolve()), 1, 1, "2023-05-14T10:00:01", 2023, 5, 14, "video", 9),
            (folder_root, str(self.video.resolve()), 1, 1, "2022-05-14T18:00:00", 2022, 5, 14, "video", 9),
        ])
        repair_live_photos(connection, folder_root)
        connection.commit()
        connection.close()

    def test_day_shows_the_live_photo_once(self):
        self.insert_rows()
        records = self.repository.matches_for_date(self.library, date(2025, 5, 14), "All")
        self.assertEqual([record.path.name for record in records], ["IMG_4330.HEIC", "Birthday.mov"])
        self.assertTrue(records[0].is_live)
        self.assertEqual(records[0].live_video, self.clip.resolve())
        self.assertFalse(records[1].is_live)

    def test_filters_count_a_live_photo_as_a_photo(self):
        self.insert_rows()
        photos = self.repository.matches_for_date(self.library, date(2025, 5, 14), "Photos")
        videos = self.repository.matches_for_date(self.library, date(2025, 5, 14), "Videos")
        self.assertEqual([record.path.name for record in photos], ["IMG_4330.HEIC"])
        self.assertTrue(photos[0].is_live)
        self.assertEqual([record.path.name for record in videos], ["Birthday.mov"])

    def test_video_library_insights_and_previews_leave_out_the_clip(self):
        self.insert_rows()
        self.assertEqual([record.path.name for record in self.repository.all_videos(self.library)], ["Birthday.mov"])
        result = self.repository.library_analytics(self.library)
        self.assertEqual((result.total_photos, result.total_videos, result.combined_total), (1, 1, 2))
        self.assertEqual(sorted(item.path.name for item in self.repository.preview_items(self.library)),
                         ["Birthday.mov", "IMG_4330.HEIC"])

    def test_missing_clip_shows_the_still_alone(self):
        self.insert_rows()
        self.clip.unlink()
        records = self.repository.matches_for_date(self.library, date(2025, 5, 14), "Photos")
        self.assertFalse(records[0].is_live)

    def test_removing_the_photo_turns_the_clip_into_a_video(self):
        self.insert_rows()
        self.repository.remove(self.library, self.photo)
        videos = self.repository.matches_for_date(self.library, date(2025, 5, 14), "Videos")
        self.assertEqual(sorted(record.path.name for record in videos), ["Birthday.mov", "IMG_4330.MOV"])

    def test_existing_index_is_paired_when_upgraded(self):
        # An index from before Live Photos: no live_pair column yet.
        self.app_dir.mkdir()
        connection = sqlite3.connect(database.DB_FILE)
        connection.execute("""
            CREATE TABLE photos (
                folder_root TEXT NOT NULL, file_path TEXT NOT NULL, file_size INTEGER NOT NULL,
                modified_ns INTEGER NOT NULL, capture_ts TEXT, capture_year INTEGER, capture_month INTEGER,
                capture_day INTEGER, media_type TEXT DEFAULT 'image', video_metadata_version INTEGER DEFAULT 0,
                PRIMARY KEY (folder_root, file_path))
        """)
        folder_root = str(self.library.resolve())
        connection.executemany(INSERT_ROW, [
            (folder_root, str(self.photo.resolve()), 1, 1, "2023-05-14T10:00:00", 2023, 5, 14, "image", 9),
            (folder_root, str(self.clip.resolve()), 1, 1, "2023-05-14T10:00:01", 2023, 5, 14, "video", 9),
            (folder_root, str(self.video.resolve()), 1, 1, "2022-05-14T18:00:00", 2022, 5, 14, "video", 9),
        ])
        connection.commit()
        connection.close()
        # The first open adds the column and pairs what's already indexed.
        records = self.repository.matches_for_date(self.library, date(2025, 5, 14), "All")
        self.assertEqual([record.path.name for record in records], ["IMG_4330.HEIC", "Birthday.mov"])

    def test_scan_pairs_and_counts_the_live_photo_once(self):
        dates = {
            "IMG_4330.HEIC": datetime(2023, 5, 14, 10, 0, 0),
            "IMG_4330.MOV": datetime(2023, 5, 14, 10, 0, 1),
            "Birthday.mov": datetime(2022, 5, 14, 18, 0, 0),
        }
        events = []
        with patch.object(indexer, "HEIC_ENABLED", True), \
                patch.object(indexer, "get_capture_date", side_effect=lambda path, _type: dates[path.name]):
            MediaIndexer(self.library, threading.Event(), 1, events.append).run()
        done = events[-1]
        self.assertEqual(done["type"], "scan_complete")
        self.assertEqual((done["total_indexed"], done["total_videos"], done["live_photos"]), (2, 1, 1))
        records = self.repository.matches_for_date(self.library, date(2025, 5, 14), "All")
        self.assertTrue(records[0].is_live)

    def test_scan_reports_when_only_the_pairing_changed(self):
        dates = {
            "IMG_4330.HEIC": datetime(2023, 5, 14, 10, 0, 0),
            "IMG_4330.MOV": datetime(2023, 5, 14, 10, 0, 1),
            "Birthday.mov": datetime(2022, 5, 14, 18, 0, 0),
        }

        def scan(scan_id: int) -> dict:
            events = []
            with patch.object(indexer, "HEIC_ENABLED", True), \
                    patch.object(indexer, "get_capture_date", side_effect=lambda path, _type: dates[path.name]):
                MediaIndexer(self.library, threading.Event(), scan_id, events.append).run()
            return events[-1]

        self.assertTrue(scan(1)["pairs_changed"], "the first scan links the photo and its clip")
        again = scan(2)
        self.assertEqual((again["updated"], again["pairs_changed"]), (0, False), "nothing changed")
        # The files are untouched, but the index groups them differently (as after an older version).
        connection = database.open_database()
        connection.execute("UPDATE photos SET live_pair = NULL")
        connection.commit()
        connection.close()
        repaired = scan(3)
        self.assertEqual((repaired["updated"], repaired["deleted"], repaired["pairs_changed"]), (0, 0, True))
        self.assertEqual(repaired["live_photos"], 1)


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.temp.name)
        self.live = ViewerItem(root / "IMG_1.HEIC", datetime(2023, 5, 14), "image", 1, 1, root / "IMG_1.MOV")
        self.plain = ViewerItem(root / "IMG_2.JPG", datetime(2023, 5, 14), "image", 1, 1)
        self.viewer = ViewerPage()
        self.viewer.resize(900, 600)
        self.viewer.show()

    def tearDown(self):
        self.viewer.shutdown()
        self.viewer.deleteLater()
        self.temp.cleanup()

    def test_live_button_shows_only_for_live_photos(self):
        self.viewer.show_items([self.live, self.plain], 0)
        self.assertTrue(self.viewer.live_button.isVisible())
        self.viewer.step(1)
        self.assertFalse(self.viewer.live_button.isVisible())

    def test_playing_switches_to_the_clip_and_back(self):
        self.viewer.show_items([self.live], 0)
        with patch.object(self.viewer.video, "load") as load:
            self.viewer.play_live()
            load.assert_called_once_with(self.live.live_video)
        self.assertIs(self.viewer.content.currentWidget(), self.viewer.video)
        self.viewer.play_live()  # pressed again: back to the still
        self.assertIs(self.viewer.content.currentWidget(), self.viewer.canvas)
        self.assertTrue(self.viewer.zoom_label.isVisible())

    def test_offline_disables_playback(self):
        self.viewer.set_offline(True)
        self.viewer.show_items([self.live], 0)
        self.assertFalse(self.viewer.live_button.isEnabled())
        with patch.object(self.viewer.video, "load") as load:
            self.viewer.play_live()
            load.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class LiveFailureTests(ViewerTests):
    def test_unplayable_clip_returns_to_the_still(self):
        self.viewer.show_items([self.live, self.plain], 0)
        with patch.object(self.viewer.video, "load"):
            self.viewer.play_live()
        self.viewer._live_failed()
        self.assertIs(self.viewer.content.currentWidget(), self.viewer.canvas)
        self.assertFalse(self.viewer.live_button.isEnabled())
        self.viewer.step(1)
        self.viewer.step(-1)  # back again: it may play now (say, the drive was reconnected)
        self.assertTrue(self.viewer.live_button.isEnabled())
