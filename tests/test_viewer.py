import tempfile
import unittest
from pathlib import Path

from PIL import Image

from onthisday.core import media
from onthisday.core.models import VideoRecord, ViewerItem
from onthisday.core.zoom import MAX_SCALE, ZoomState


class ZoomStateTests(unittest.TestCase):
    def test_fits_large_image_inside_view(self):
        state = ZoomState.fitted(4000, 3000, 800, 800)
        self.assertAlmostEqual(state.scale, 0.2)
        x, y, width, height = state.target_rect()
        self.assertEqual((x, width), (0, 800))
        self.assertAlmostEqual(y, 100)
        self.assertAlmostEqual(height, 600)

    def test_never_enlarges_small_image(self):
        state = ZoomState.fitted(200, 100, 1000, 800)
        self.assertEqual(state.scale, 1.0)
        self.assertTrue(state.is_fitted)

    def test_zoom_keeps_point_under_cursor(self):
        state = ZoomState.fitted(4000, 3000, 800, 600)
        anchor = (600.0, 150.0)
        before = (state.cx + (anchor[0] - 400) / state.scale, state.cy + (anchor[1] - 300) / state.scale)
        zoomed = state.with_scale(state.scale * 3, anchor)
        after = (zoomed.cx + (anchor[0] - 400) / zoomed.scale, zoomed.cy + (anchor[1] - 300) / zoomed.scale)
        self.assertAlmostEqual(before[0], after[0])
        self.assertAlmostEqual(before[1], after[1])

    def test_scale_limits(self):
        state = ZoomState.fitted(4000, 3000, 800, 600)
        self.assertEqual(state.with_scale(100).scale, MAX_SCALE)
        self.assertEqual(state.with_scale(0.0001).scale, state.fit_scale)

    def test_pan_is_clamped_to_image_edges(self):
        state = ZoomState.fitted(4000, 3000, 800, 600).with_scale(1.0)
        far = state.panned(1_000_000, 1_000_000)  # drag towards the top-left corner
        x, y, _width, _height = far.target_rect()
        self.assertAlmostEqual(x, 0)
        self.assertAlmostEqual(y, 0)
        # A fitted image can't be panned at all.
        fitted = ZoomState.fitted(4000, 3000, 800, 600)
        self.assertEqual(fitted.panned(50, 50), fitted)

    def test_resize_keeps_fit(self):
        state = ZoomState.fitted(4000, 3000, 800, 600).resized(1600, 1200)
        self.assertTrue(state.is_fitted)
        self.assertAlmostEqual(state.scale, 0.4)
        zoomed = ZoomState.fitted(4000, 3000, 800, 600).with_scale(1.0).resized(1600, 1200)
        self.assertEqual(zoomed.scale, 1.0)


class DisplayImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_exif_orientation_6_is_rotated(self):
        source = self.root / "phone.jpg"
        exif = Image.Exif()
        exif[0x0112] = 6  # stored landscape, displayed portrait
        Image.new("RGB", (400, 300), "red").save(source, exif=exif)
        image = media.load_display_image(source, 4000)
        self.assertEqual(image.size, (300, 400))

    def test_display_size_applies_rotation_without_decoding(self):
        source = self.root / "rotated.jpg"
        exif = Image.Exif()
        exif[0x0112] = 6
        Image.new("RGB", (400, 300)).save(source, exif=exif)
        self.assertEqual(media.display_size(source), (300, 400))

    def test_longest_edge_is_capped(self):
        source = self.root / "large.png"
        Image.new("RGB", (5000, 2000), "blue").save(source)
        image = media.load_display_image(source, 1000)
        self.assertEqual(max(image.size), 1000)
        self.assertEqual(image.size, (1000, 400))

    def test_letterbox_padding_is_found(self):
        thumb = Image.new("RGB", (496, 372), media.THUMBNAIL_PADDING)
        thumb.paste(Image.new("RGB", (279, 372), (200, 120, 60)), (108, 0))  # a portrait photo
        rect = media.letterbox_content_rect(496, 372, lambda x, y: thumb.getpixel((x, y)))
        self.assertEqual(rect, (108, 0, 279, 372))

    def test_letterbox_rejects_dark_photo(self):
        dark = Image.new("RGB", (496, 372), media.THUMBNAIL_PADDING)
        dark.paste(Image.new("RGB", (40, 40), "white"), (228, 166))  # mostly "padding" on both axes
        self.assertIsNone(media.letterbox_content_rect(496, 372, lambda x, y: dark.getpixel((x, y))))


class ViewerItemTests(unittest.TestCase):
    def test_video_rows_without_dates_are_kept(self):
        path = Path("/clip.mov")
        item = ViewerItem.from_video(VideoRecord(path, None, 10, 20))
        self.assertIsNone(item.captured_at)
        self.assertTrue(item.is_video)
        self.assertEqual(item.key, (str(path), 20))  # "\clip.mov" on Windows

    def test_duration_format(self):
        self.assertEqual(media.format_duration(65_400), "1:05")
        self.assertEqual(media.format_duration(3_725_000), "1:02:05")


if __name__ == "__main__":
    unittest.main()
