import json
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from onthisday.core import database, settings
from onthisday.core.indexer import MediaIndexer
from onthisday.core.settings import SettingsStore


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app_dir = self.root / "app-data"
        self.db_file = self.app_dir / "photo_index.sqlite3"
        self.thumb_dir = self.app_dir / "thumbnails"
        self.config_file = self.app_dir / "config.json"
        self.patches = [
            patch.object(database, "APP_DIR", self.app_dir),
            patch.object(database, "DB_FILE", self.db_file),
            patch.object(database, "THUMBNAIL_DIR", self.thumb_dir),
            patch.object(settings, "APP_DIR", self.app_dir),
            patch.object(settings, "CONFIG_FILE", self.config_file),
            patch.object(settings, "THUMBNAIL_DIR", self.thumb_dir),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_settings_preserve_unknown_values(self):
        self.app_dir.mkdir()
        self.config_file.write_text(json.dumps({"photo_folder": str(self.root), "legacy": 42}))
        store = SettingsStore()
        loaded = store.load()
        self.assertEqual(loaded.photo_folder, self.root)
        loaded.theme = "dark"
        store.save(loaded)
        saved = json.loads(self.config_file.read_text())
        self.assertEqual(saved["legacy"], 42)
        self.assertEqual(saved["theme"], "dark")

    def test_repository_filters_and_orders_existing_schema(self):
        media_root = self.root / "media"
        media_root.mkdir()
        photo, video = media_root / "photo.jpg", media_root / "clip.mov"
        photo.touch()
        video.touch()
        connection = database.open_database()
        folder_root = str(media_root.resolve())
        rows = [
            (folder_root, str(photo), 1, 1, "2025-09-13T08:00:00", 2025, 9, 13, "image", 0),
            (folder_root, str(video), 1, 1, "2024-09-13T09:00:00", 2024, 9, 13, "video", 5),
        ]
        connection.executemany("INSERT INTO photos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        connection.commit()
        connection.close()
        repository = database.MediaRepository()
        self.assertEqual(len(repository.matches_for_date(media_root, date(2026, 9, 13), "All")), 2)
        self.assertEqual(repository.matches_for_date(media_root, date(2026, 9, 13), "Photos")[0].path, photo)
        self.assertEqual(repository.all_videos(media_root)[0].path, video)

    def test_indexer_scans_and_emits_completion(self):
        media_root = self.root / "library"
        media_root.mkdir()
        image_path = media_root / "sample.jpg"
        Image.new("RGB", (32, 24), "navy").save(image_path)
        events = []
        MediaIndexer(media_root, threading.Event(), 7, events.append).run()
        self.assertEqual(events[0]["type"], "scan_started")
        self.assertEqual(events[-1]["type"], "scan_complete")
        self.assertEqual(events[-1]["total_indexed"], 1)

    def insert_analytics_rows(self, folder: Path, rows: list[tuple[str, int | None, int | None, int | None]]) -> None:
        """Insert (media_type, year, month, day) rows for repository tests."""
        connection = database.open_database()
        folder_root = str(folder.resolve())
        values = []
        for index, (media_type, year, month, day) in enumerate(rows):
            timestamp = None
            if year is not None and month is not None and day is not None:
                timestamp = f"{year:04d}-{month:02d}-{day:02d}T12:00:00"
            values.append((
                folder_root, str(folder / f"media-{index}"), index + 1, index + 1,
                timestamp, year, month, day, media_type, 0,
            ))
        connection.executemany("INSERT INTO photos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
        connection.commit()
        connection.close()

    def test_analytics_photo_video_and_combined_totals(self):
        folder = self.root / "totals"
        self.insert_analytics_rows(folder, [
            ("image", 2020, 1, 1), ("image", 2021, 2, 2), ("video", 2022, 3, 3),
        ])
        result = database.MediaRepository().library_analytics(folder)
        self.assertEqual((result.total_photos, result.total_videos, result.combined_total), (2, 1, 3))

    def test_analytics_busiest_day_including_february_29(self):
        folder = self.root / "days"
        self.insert_analytics_rows(folder, [
            ("image", 2020, 2, 29), ("video", 2024, 2, 29),
            ("image", 2021, 7, 18),
        ])
        result = database.MediaRepository().library_analytics(folder)
        self.assertEqual(result.busiest_day, (2, 29))
        self.assertEqual(result.busiest_day_count, 2)

    def test_analytics_largest_year_and_media_grouped_by_year(self):
        folder = self.root / "years"
        self.insert_analytics_rows(folder, [
            ("image", 2019, 1, 1),
            ("video", 2021, 1, 1), ("image", 2021, 2, 2), ("video", 2021, 3, 3),
            ("image", 2020, 4, 4), ("image", 2020, 5, 5),
        ])
        result = database.MediaRepository().library_analytics(folder)
        self.assertEqual((result.largest_year, result.largest_year_count), (2021, 3))
        self.assertEqual(
            [(row.year, row.photos, row.videos) for row in result.media_by_year],
            [(2019, 1, 0), (2020, 2, 0), (2021, 1, 2)],
        )

    def test_analytics_most_active_month(self):
        folder = self.root / "months"
        self.insert_analytics_rows(folder, [
            ("image", 2019, 8, 1), ("video", 2020, 8, 2), ("image", 2021, 8, 3),
            ("image", 2022, 12, 4), ("video", 2023, 12, 5),
        ])
        result = database.MediaRepository().library_analytics(folder)
        self.assertEqual((result.most_active_month, result.most_active_month_count), (8, 3))

    def test_analytics_empty_database(self):
        result = database.MediaRepository().library_analytics(self.root / "empty")
        self.assertEqual((result.total_photos, result.total_videos, result.combined_total), (0, 0, 0))
        self.assertIsNone(result.busiest_day)
        self.assertIsNone(result.largest_year)
        self.assertEqual(result.media_by_year, ())
        self.assertIsNone(result.most_active_month)

    def test_analytics_are_isolated_by_folder(self):
        first, second = self.root / "first", self.root / "second"
        self.insert_analytics_rows(first, [("image", 2020, 4, 3), ("video", 2020, 4, 3)])
        self.insert_analytics_rows(second, [("video", 2024, 9, 13)])
        first_result = database.MediaRepository().library_analytics(first)
        second_result = database.MediaRepository().library_analytics(second)
        self.assertEqual((first_result.total_photos, first_result.total_videos), (1, 1))
        self.assertEqual((second_result.total_photos, second_result.total_videos), (0, 1))
        self.assertEqual(first_result.busiest_day, (4, 3))
        self.assertEqual(second_result.busiest_day, (9, 13))

    def test_analytics_ignore_only_missing_required_date_values(self):
        folder = self.root / "partial-dates"
        self.insert_analytics_rows(folder, [
            ("image", None, None, None),
            ("video", 2020, None, None),
            ("image", None, 6, None),
            ("image", None, 6, 15),
        ])
        result = database.MediaRepository().library_analytics(folder)
        self.assertEqual(result.combined_total, 4)
        self.assertEqual((result.largest_year, result.largest_year_count), (2020, 1))
        self.assertEqual(result.busiest_day, (6, 15))
        self.assertEqual((result.most_active_month, result.most_active_month_count), (6, 2))
        self.assertEqual([(row.year, row.total) for row in result.media_by_year], [(2020, 1)])

    def test_analytics_ties_choose_earliest_calendar_value(self):
        folder = self.root / "ties"
        self.insert_analytics_rows(folder, [
            ("image", 2022, 7, 18), ("video", 2022, 7, 18),
            ("image", 2020, 3, 20), ("video", 2020, 3, 20),
        ])
        result = database.MediaRepository().library_analytics(folder)
        self.assertEqual(result.busiest_day, (3, 20))
        self.assertEqual(result.largest_year, 2020)
        self.assertEqual(result.most_active_month, 3)


if __name__ == "__main__":
    unittest.main()
