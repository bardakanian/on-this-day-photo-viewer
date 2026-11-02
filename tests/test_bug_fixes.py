"""Regression tests for the bugs fixed in 1.5.1."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import threading
import time
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from PySide6.QtWidgets import QApplication

from onthisday.core import database, media
from onthisday.core.database import MediaRepository
from onthisday.core.indexer import MediaIndexer
from onthisday.core.models import MediaRecord, VideoRecord
from onthisday.ui.pages.gallery_page import GalleryPage, YearSection
from onthisday.ui.pages.videos_page import VideosPage

APP = QApplication.instance() or QApplication([])


class IsolatedAppData(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        app_dir = self.root / "app-data"
        self.thumb_dir = app_dir / "thumbnails"
        self.patches = [
            patch.object(database, "APP_DIR", app_dir),
            patch.object(database, "DB_FILE", app_dir / "photo_index.sqlite3"),
            patch.object(database, "THUMBNAIL_DIR", self.thumb_dir),
            patch.object(media, "THUMBNAIL_DIR", self.thumb_dir),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()


def save_with_exif(path: Path, original: str | None = None, modified: str | None = None) -> None:
    exif = Image.Exif()
    if modified:
        exif[306] = modified
    if original:
        exif.get_ifd(0x8769)[36867] = original  # DateTimeOriginal lives in the Exif sub-IFD
    Image.new("RGB", (16, 12), "red").save(path, exif=exif.tobytes())


class ExifDateTests(IsolatedAppData):
    def test_date_taken_wins_over_last_edit(self):
        path = self.root / "edited.jpg"
        save_with_exif(path, original="2015:07:04 12:00:00", modified="2024:05:05 10:00:00")
        self.assertEqual(media.get_image_exif_date(path), datetime(2015, 7, 4, 12))

    def test_date_taken_alone_is_found(self):
        path = self.root / "camera.jpg"
        save_with_exif(path, original="2015:07:04 12:00:00")
        self.assertEqual(media.get_image_exif_date(path), datetime(2015, 7, 4, 12))

    def test_placeholder_date_taken_falls_back_to_next_tag(self):
        path = self.root / "unset-clock.jpg"
        save_with_exif(path, original="1980:01:01 00:00:00", modified="2019:03:02 10:00:00")
        self.assertEqual(media.get_image_exif_date(path), datetime(2019, 3, 2, 10))


class AtomicThumbnailTests(IsolatedAppData):
    def test_thumbnail_appears_only_when_complete(self):
        source = self.root / "photo.jpg"
        Image.new("RGB", (400, 300), "red").save(source)
        target = media.thumbnail_cache_path(source, 1, 1)
        real_save = Image.Image.save
        seen_while_writing = []

        def save(image, file, *args, **kwargs):
            Path(file).write_bytes(b"\xff\xd8 half a JPEG")
            # What a reader (or the next launch, if the app quit now) would find at this moment.
            seen_while_writing.append(target.exists())
            return real_save(image, file, *args, **kwargs)

        with patch.object(Image.Image, "save", save):
            self.assertEqual(media.get_cached_thumbnail(source, "image", 1, 1), target)
        self.assertEqual(seen_while_writing, [False], "a half-written thumbnail would be served forever")
        with Image.open(target) as result:
            self.assertEqual(result.size, media.THUMBNAIL_SIZE)
        self.assertEqual(list(self.thumb_dir.glob("*.part")), [])

    def test_prune_removes_only_old_partial_files(self):
        self.thumb_dir.mkdir(parents=True)
        old, recent = self.thumb_dir / "a.1-2.part", self.thumb_dir / "b.1-2.part"
        old.touch()
        recent.touch()
        stale = time.time() - 2 * 3600
        os.utime(old, (stale, stale))
        media.prune_thumbnail_cache([])
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists(), "a recent .part file may still be being written")


class HiddenFileTests(IsolatedAppData):
    def test_hidden_and_system_files_are_not_indexed(self):
        library = self.root / "library"
        library.mkdir()
        Image.new("RGB", (8, 8)).save(library / "IMG_1.jpg")
        (library / "._IMG_1.jpg").write_bytes(b"\x00\x05\x16\x07" + b"\x00" * 64)  # AppleDouble
        for folder in (".Trashes/501", "@eaDir/IMG_1.jpg", "$RECYCLE.BIN"):
            (library / folder).mkdir(parents=True)
            Image.new("RGB", (8, 8)).save(library / folder / "copy.jpg")
        events = []
        MediaIndexer(library, threading.Event(), 1, events.append).run()
        self.assertEqual(events[-1]["type"], "scan_complete")
        self.assertEqual(events[-1]["total_indexed"], 1)


class LeapDayTests(IsolatedAppData):
    def setUp(self):
        super().setUp()
        self.library = self.root / "library"
        self.library.mkdir()
        connection = database.open_database()
        for name, month, day in (("leap.jpg", 2, 29), ("feb28.jpg", 2, 28)):
            path = self.library / name
            path.touch()
            connection.execute(
                "INSERT INTO photos (folder_root, file_path, file_size, modified_ns, capture_ts, capture_year,"
                " capture_month, capture_day, media_type) VALUES (?, ?, 0, 0, ?, 2020, ?, ?, 'image')",
                (str(self.library.resolve()), str(path.resolve()), f"2020-{month:02d}-{day:02d}T10:00:00", month, day),
            )
        connection.commit()
        connection.close()

    def names(self, day: date) -> set[str]:
        return {record.path.name for record in MediaRepository().matches_for_date(self.library, day, "All")}

    def test_leap_day_media_shows_on_february_28_in_other_years(self):
        self.assertEqual(self.names(date(2026, 2, 28)), {"leap.jpg", "feb28.jpg"})

    def test_leap_years_keep_the_days_apart(self):
        self.assertEqual(self.names(date(2028, 2, 28)), {"feb28.jpg"})
        self.assertEqual(self.names(date(2028, 2, 29)), {"leap.jpg"})


class GalleryRefreshTests(unittest.TestCase):
    def test_refreshing_the_same_day_keeps_loaded_and_collapsed_years(self):
        records = [MediaRecord(Path(f"/missing/{year}-{index}.jpg"), datetime(year, 5, 1), "image", 1, 1)
                   for year in (2020, 2019) for index in range(150)]
        gallery = GalleryPage()
        gallery.show_records(records, date(2026, 5, 1), "All", Path("/missing"))
        first, second = gallery.content.findChildren(YearSection)
        first.render_more(60)  # "Load more"
        second._toggle()       # collapse
        gallery.show_records(records[1:], date(2026, 5, 1), "All", Path("/missing"))  # one item deleted
        first, second = gallery.content.findChildren(YearSection)
        self.assertEqual(first.rendered, 120)
        self.assertFalse(second.expanded)
        gallery.cancel_pending()


class VideoCountTests(unittest.TestCase):
    def test_count_respects_active_search_after_refresh(self):
        page = VideosPage()
        rows = [VideoRecord(Path(f"/v/{name}.mov"), None, 1, 1) for name in ("beach", "birthday", "hike")]
        page.set_records(rows)
        page.search.setText("bi")
        page.set_records(rows)  # Refresh
        self.assertEqual(page.count.text(), "1 of 3 videos")


if __name__ == "__main__":
    unittest.main()
