import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from onthisday.core import database, indexer, media, settings
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
            patch.object(media, "THUMBNAIL_DIR", self.thumb_dir),
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

    def test_repository_removes_only_requested_folder_record(self):
        first = self.root / "first"
        second = self.root / "second"
        first.mkdir()
        second.mkdir()
        shared_name = "photo.jpg"
        first_photo = first / shared_name
        second_photo = second / shared_name
        first_photo.touch()
        second_photo.touch()
        connection = database.open_database()
        rows = [
            (str(first.resolve()), str(first_photo.resolve()), 1, 1, "2025-09-13T08:00:00", 2025, 9, 13, "image", 0),
            (str(second.resolve()), str(second_photo.resolve()), 1, 1, "2025-09-13T08:00:00", 2025, 9, 13, "image", 0),
        ]
        connection.executemany("INSERT INTO photos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        connection.commit()
        connection.close()

        repository = database.MediaRepository()
        self.assertTrue(repository.remove(first, first_photo))
        self.assertFalse(repository.remove(first, first_photo))
        self.assertEqual(len(repository.matches_for_date(first, date(2026, 9, 13), "All")), 0)
        self.assertEqual(len(repository.matches_for_date(second, date(2026, 9, 13), "All")), 1)

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

    def test_image_thumbnail_respects_exif_rotation(self):
        source = self.root / "rotated.jpg"
        exif = Image.Exif()
        exif[0x0112] = 6  # Rotate 90° clockwise when displayed
        Image.new("RGB", (4000, 3000), "red").save(source, exif=exif)
        thumbnail = media.get_cached_thumbnail(source, "image", 1, 1)
        with Image.open(thumbnail) as result:
            self.assertEqual(result.size, media.THUMBNAIL_SIZE)
            # Portrait after rotation: padded at the sides, image in the middle.
            self.assertLess(sum(result.getpixel((5, result.height // 2))), 100)
            self.assertGreater(result.getpixel((result.width // 2, result.height // 2))[0], 200)

    def test_failed_thumbnail_is_not_retried(self):
        source = self.root / "broken.jpg"
        source.write_bytes(b"not an image")
        self.assertIsNone(media.get_cached_thumbnail(source, "image", 1, 1))
        with patch.object(media, "_image_thumbnail") as generate:
            self.assertIsNone(media.get_cached_thumbnail(source, "image", 1, 1))
            generate.assert_not_called()
        # A changed file (new size/mtime) gets a fresh attempt.
        with patch.object(media, "_image_thumbnail") as generate:
            media.get_cached_thumbnail(source, "image", 2, 2)
            generate.assert_called_once()

    def test_missing_source_is_retried_later(self):
        source = self.root / "unmounted" / "photo.jpg"
        self.assertIsNone(media.get_cached_thumbnail(source, "image", 1, 1))
        self.assertEqual([path for path in media.thumbnail_cache_files(source, 1, 1) if path.exists()], [])

    @unittest.skipUnless(media.FFMPEG_ENABLED, "ffmpeg not installed")
    def test_video_shorter_than_one_second_gets_thumbnail(self):
        import subprocess
        source = self.root / "short.mp4"
        subprocess.run([
            media.imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=0.4",
            "-pix_fmt", "yuv420p", str(source),
        ], capture_output=True, check=True)
        thumbnail = media.get_cached_thumbnail(source, "video", 1, 1)
        self.assertIsNotNone(thumbnail)
        with Image.open(thumbnail) as result:
            self.assertEqual(result.size, media.THUMBNAIL_SIZE)

    def test_indexer_reads_dates_in_parallel(self):
        media_root = self.root / "parallel"
        media_root.mkdir()
        for day in range(1, 41):
            exif = Image.Exif()
            exif[306] = f"2019:03:{day % 28 + 1:02d} 10:00:00"
            Image.new("RGB", (8, 8)).save(media_root / f"photo-{day}.jpg", exif=exif)
        events = []
        MediaIndexer(media_root, threading.Event(), 1, events.append).run()
        self.assertEqual(events[-1]["type"], "scan_complete")
        self.assertEqual((events[-1]["total_indexed"], events[-1]["updated"], events[-1]["errors"]), (40, 40, 0))
        connection = database.open_database()
        dates = {Path(path).name: ts for path, ts in connection.execute("SELECT file_path, capture_ts FROM photos")}
        connection.close()
        self.assertEqual(dates["photo-5.jpg"], "2019-03-06T10:00:00")
        # A second scan finds everything unchanged and reads no metadata.
        events = []
        with patch.object(indexer, "get_capture_date") as read_date:
            MediaIndexer(media_root, threading.Event(), 2, events.append).run()
            read_date.assert_not_called()
        self.assertEqual(events[-1]["unchanged"], 40)

    def test_indexer_counts_metadata_errors_per_file(self):
        media_root = self.root / "errors"
        media_root.mkdir()
        for name in ("good.jpg", "bad.jpg"):
            Image.new("RGB", (8, 8)).save(media_root / name)
        real = indexer.get_capture_date

        def flaky(path, media_type):
            if path.name == "bad.jpg":
                raise RuntimeError("unreadable")
            return real(path, media_type)

        events = []
        with patch.object(indexer, "get_capture_date", side_effect=flaky):
            MediaIndexer(media_root, threading.Event(), 1, events.append).run()
        self.assertEqual((events[-1]["errors"], events[-1]["total_indexed"]), (1, 1))

    def test_indexer_cancel_stops_scan(self):
        media_root = self.root / "cancel"
        media_root.mkdir()
        for index in range(20):
            Image.new("RGB", (8, 8)).save(media_root / f"{index}.jpg")
        stop = threading.Event()

        def stop_on_first(path, media_type):
            stop.set()
            return None

        events = []
        with patch.object(indexer, "get_capture_date", side_effect=stop_on_first):
            MediaIndexer(media_root, stop, 1, events.append).run()
        self.assertEqual(events[-1]["type"], "scan_cancelled")

    def test_unchanged_files_from_an_older_version_are_reread_once(self):
        library = self.root / "library"
        library.mkdir()
        photo = library / "screenshot.png"
        Image.new("RGB", (8, 8)).save(photo)
        made = datetime(2026, 1, 3, 7, 52, 14)
        os.utime(photo, (made.timestamp(), made.timestamp()))
        stat = photo.stat()
        # A row written by the old version: dated by the copy time, version 0.
        connection = database.open_database()
        connection.execute("INSERT INTO photos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            str(library.resolve()), str(photo.resolve()), stat.st_size, stat.st_mtime_ns,
            "2026-06-26T18:09:53", 2026, 6, 26, "image", 0,
        ))
        connection.commit()
        connection.close()

        with patch.object(media, "parse_macos_metadata_date", return_value=None):
            events = []
            MediaIndexer(library, threading.Event(), 1, events.append).run()
            self.assertEqual((events[-1]["updated"], events[-1]["unchanged"]), (1, 0))
            connection = database.open_database()
            stored = connection.execute("SELECT capture_ts FROM photos").fetchone()[0]
            connection.close()
            self.assertEqual(stored, "2026-01-03T07:52:14")
            # The next scan leaves it alone.
            events = []
            MediaIndexer(library, threading.Event(), 2, events.append).run()
            self.assertEqual((events[-1]["updated"], events[-1]["unchanged"]), (0, 1))

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



class CopiedFileDateTests(unittest.TestCase):
    """Files without embedded dates that were copied (backups, exports) after they were made.

    Regression: they were dated by the copy time, so a backup made in June showed January
    photos on a June day.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def copied_file(self, name, made, data=None):
        path = self.root / name
        if data is None:
            Image.new("RGB", (8, 8), "teal").save(path)  # no EXIF
        else:
            path.write_bytes(data)
        stamp = made.timestamp()
        os.utime(path, (stamp, stamp))  # modification time survives a copy; creation time is "now"
        return path

    def test_image_without_metadata_uses_earliest_file_time(self):
        made = datetime(2026, 1, 3, 7, 52, 14)
        with patch.object(media, "parse_macos_metadata_date", return_value=None):
            self.assertEqual(media.get_capture_date(self.copied_file("screenshot.png", made), "image"), made)

    def test_video_without_metadata_uses_earliest_file_time(self):
        made = datetime(2026, 1, 2, 22, 9, 34)
        path = self.copied_file("clip.mp4", made, data=b"not really a video")
        with patch.object(media, "parse_macos_metadata_date", return_value=None):
            self.assertEqual(media.get_capture_date(path, "video"), made)

    def test_spotlight_copy_time_is_ignored(self):
        copy_time = datetime(2026, 6, 26, 18, 9, 53)
        self.assertIsNone(media.choose_spotlight_date(copy_time, copy_time))
        self.assertIsNone(media.choose_spotlight_date(copy_time, copy_time + timedelta(seconds=1)))
        self.assertIsNone(media.choose_spotlight_date(None, copy_time))
        taken = datetime(2026, 1, 3, 7, 52)
        self.assertEqual(media.choose_spotlight_date(taken, copy_time), taken)

    @unittest.skipUnless(sys.platform == "darwin", "Spotlight is macOS-only")
    def test_spotlight_lookup_parses_both_fields(self):
        def fake_mdls(stdout):
            return patch.object(media.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout, ""))

        with fake_mdls("2026-06-27 01:09:53 +0000\x002026-06-27 01:09:53 +0000"):
            self.assertIsNone(media.parse_macos_metadata_date(self.root / "x.jpg"))
        expected = datetime.fromisoformat("2026-01-03 15:52:14+00:00").astimezone().replace(tzinfo=None)
        with fake_mdls("2026-01-03 15:52:14 +0000\x002026-06-27 01:09:53 +0000"):
            self.assertEqual(media.parse_macos_metadata_date(self.root / "x.jpg"), expected)


class PlaceholderDateTests(unittest.TestCase):
    """Epoch and unset-clock dates (1969/1970, 1980, 1904, far future) are not capture dates."""

    def test_placeholder_dates(self):
        for value in (datetime(1969, 12, 31, 16, 0), datetime(1970, 1, 1), datetime(1980, 1, 1, 0, 0, 45),
                      datetime(1904, 1, 1), datetime(1899, 5, 1), datetime(datetime.now().year + 2, 1, 1)):
            self.assertTrue(media.is_placeholder_date(value), value)
        for value in (datetime(2026, 1, 3, 7, 52), datetime(1999, 11, 16, 16, 40), datetime(1980, 1, 3),
                      datetime(1971, 6, 1)):
            self.assertFalse(media.is_placeholder_date(value), value)

    def test_unset_camera_clock_falls_back_to_file_time(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "IMG_7469.JPG"
            exif = Image.Exif()
            exif[306] = "1980:01:01 00:00:06"  # what a camera with an unset clock writes
            Image.new("RGB", (8, 8)).save(path, exif=exif)
            made = datetime(2017, 8, 16, 17, 26, 0)
            os.utime(path, (made.timestamp(), made.timestamp()))
            with patch.object(media, "parse_macos_metadata_date", return_value=None):
                self.assertEqual(media.get_capture_date(path, "image"), made)

if __name__ == "__main__":
    unittest.main()
