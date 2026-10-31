"""Viewer widgets, run with Qt's off-screen platform so no display is needed."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from onthisday.core.models import ViewerItem
from onthisday.ui import viewer_images
from onthisday.ui.pages.viewer_page import ViewerPage
from onthisday.ui.widgets.image_canvas import ImageCanvas

APP = QApplication.instance() or QApplication([])


def pixmap(width: int, height: int) -> QPixmap:
    result = QPixmap(width, height)
    result.fill()
    return result


class LoadingMessageTests(unittest.TestCase):
    """Regression: a photo that arrived while "Loading…" showed was never drawn (black screen)."""

    def test_photo_after_loading_message_is_drawn_at_its_own_size(self):
        canvas = ImageCanvas()
        canvas.resize(1000, 700)
        canvas.set_content(pixmap(400, 300), (4032, 3024))  # previous photo, decoder knew its size
        canvas.set_message("Loading…")
        canvas.set_pixmap(pixmap(400, 600), (2000, 3000))   # the next photo's decode arrives
        self.assertIsNotNone(canvas._state, "no zoom state: the photo would never be drawn")
        self.assertEqual(canvas._natural, (2000, 3000))     # not the previous photo's size
        self.assertTrue(canvas.is_fitted)
        x, y, width, height = canvas._state.target_rect()
        self.assertTrue(0 <= x and 0 <= y and x + width <= 1000.5 and y + height <= 700.5)

    def test_message_forgets_previous_photo(self):
        canvas = ImageCanvas()
        canvas.resize(800, 600)
        canvas.set_content(pixmap(40, 30), (4000, 3000))
        canvas.set_message("This photo can't be displayed.")
        self.assertIsNone(canvas._natural)
        self.assertFalse(canvas.has_image)


class ViewerJumpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.items = []
        for name, size in (("a.jpg", (4032, 3024)), ("b.jpg", (3000, 2000)), ("c.jpg", (2000, 3000))):
            Image.new("RGB", size, "red").save(root / name)
            self.items.append(ViewerItem(root / name, datetime(2020, 1, 1), "image", 1, 1))

    def tearDown(self):
        self.temp.cleanup()

    def wait_until(self, condition, timeout: float = 10) -> None:
        end = time.time() + timeout
        while time.time() < end and not condition():
            APP.processEvents()
            time.sleep(0.01)
        self.assertTrue(condition(), "timed out")

    def test_jumping_to_a_photo_that_was_not_prefetched_shows_it(self):
        # No gallery thumbnail (not cached yet, or too dark to crop), so "Loading…" stays up.
        with patch.object(viewer_images, "load_placeholder", return_value=None):
            viewer = ViewerPage()
            viewer.resize(1000, 700)
            viewer.show_items(self.items, 0)
            self.wait_until(lambda: viewer._screen_decoded)
            viewer.go_to(2)  # End: only a.jpg's neighbour b.jpg was decoded ahead
            self.assertEqual(viewer.canvas._message, "Loading…")
            self.wait_until(lambda: viewer._screen_decoded)
            canvas = viewer.canvas
            self.assertTrue(canvas.has_image)
            self.assertIsNotNone(canvas._state, "black screen: photo decoded but has nowhere to be drawn")
            self.assertEqual(canvas._natural, (2000, 3000))
            viewer.shutdown()


if __name__ == "__main__":
    unittest.main()
