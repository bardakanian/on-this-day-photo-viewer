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


if __name__ == "__main__":
    unittest.main()
