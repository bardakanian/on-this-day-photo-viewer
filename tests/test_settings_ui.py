"""Settings: the Video Library button, preview quality, and notes that fit."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLabel

from onthisday.core import settings as settings_module
from onthisday.core.constants import HIGH_THUMBNAIL_EDGE, THUMBNAIL_EDGE
from onthisday.core.gallery_layout import DEFAULT_TILE, MAX_TILE
from onthisday.core.settings import PREVIEW_HIGH, PREVIEW_STANDARD, AppSettings, SettingsStore
from onthisday.ui.dialogs import PreferencesDialog
from tests.test_auto_refresh import WindowTestCase

APP = QApplication.instance() or QApplication([])


class DialogTests(unittest.TestCase):
    def dialog(self, **options) -> PreferencesDialog:
        dialog = PreferencesDialog("system", **options)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def shown(self, **options) -> PreferencesDialog:
        dialog = self.dialog(**options)
        dialog.show()
        APP.processEvents()
        APP.processEvents()
        self.addCleanup(dialog.hide)
        return dialog

    def test_every_note_is_shown_in_full(self):
        dialog = self.shown()
        clipped = [label.text() for label in dialog.findChildren(QLabel)
                   if label.wordWrap() and label.height() < label.heightForWidth(label.width())]
        self.assertEqual(clipped, [], "the dialog opened too short, cutting off explanations")

    def test_a_large_system_font_scrolls_rather_than_hiding_the_buttons(self):
        was = APP.font()
        self.addCleanup(APP.setFont, was)
        APP.setFont(QFont(was.family(), 22))  # like a high-DPI Windows setup at 150%
        dialog = self.shown()
        self.assertLessEqual(dialog.height(), dialog._room_on_screen(), "taller than the screen")
        buttons = dialog.findChild(QDialogButtonBox)
        self.assertTrue(buttons.isVisible())
        self.assertLessEqual(buttons.geometry().bottom(), dialog.height(), "Save and Cancel are off the dialog")
        clipped = [label.text() for label in dialog.findChildren(QLabel)
                   if label.wordWrap() and label.height() < label.heightForWidth(label.width())]
        self.assertEqual(clipped, [])

    def test_video_library_button_asks_to_open_it_and_closes_settings(self):
        dialog = self.dialog()
        asked = []
        dialog.open_videos_requested.connect(lambda: asked.append(True))
        dialog.open_videos.click()
        self.assertEqual(asked, [True])
        self.assertFalse(dialog.isVisible())

    def test_preview_quality_round_trips(self):
        self.assertEqual(self.dialog().selected_preview_quality, PREVIEW_HIGH)  # the default
        dialog = self.dialog(preview_quality=PREVIEW_STANDARD)
        self.assertEqual(dialog.selected_preview_quality, PREVIEW_STANDARD)
        dialog.preview_quality.setCurrentIndex(dialog.preview_quality.findData(PREVIEW_HIGH))
        self.assertEqual(dialog.selected_preview_quality, PREVIEW_HIGH)


class StoredSettingsTests(unittest.TestCase):
    def test_quality_and_tile_size_are_remembered(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.json"
            with patch.object(settings_module, "CONFIG_FILE", config), \
                    patch.object(settings_module, "APP_DIR", Path(temp)), \
                    patch.object(settings_module, "THUMBNAIL_DIR", Path(temp) / "thumbnails"):
                store = SettingsStore()
                self.assertEqual(store.load().preview_quality, PREVIEW_HIGH)  # sharp previews by default
                self.assertEqual(store.load().preview_edge, HIGH_THUMBNAIL_EDGE)
                store.save(AppSettings(Path(temp), preview_quality=PREVIEW_STANDARD, tile_size=240))
                loaded = store.load()
                self.assertEqual((loaded.preview_quality, loaded.preview_edge), (PREVIEW_STANDARD, THUMBNAIL_EDGE))
                self.assertEqual(loaded.tile_size, 240)
                # Out of range or nonsense falls back instead of breaking the gallery.
                config.write_text(json.dumps({"preview_quality": "enormous", "tile_size": "big"}))
                self.assertEqual(store.load().preview_quality, PREVIEW_HIGH)
                self.assertEqual(store.load().tile_size, DEFAULT_TILE)
                config.write_text(json.dumps({"tile_size": 10_000}))
                self.assertEqual(store.load().tile_size, MAX_TILE)


class WindowSettingsTests(WindowTestCase):
    """The window applies what Settings changed."""

    def accept_settings(self, **changes) -> None:
        def exec_dialog(dialog):
            for name, value in changes.items():
                getattr(dialog, name).setCurrentIndex(getattr(dialog, name).findData(value))
            return 1  # Save

        with patch.object(PreferencesDialog, "exec", exec_dialog), \
                patch.object(self.window, "_start_cache_job"):
            self.window.show_preferences()

    def test_switching_preview_quality_reloads_tiles_and_saves_them_again(self):
        self.assertEqual(self.window.gallery.grid.preview_edge, HIGH_THUMBNAIL_EDGE)
        with patch.object(self.window, "start_saving_previews") as saving:
            self.accept_settings(preview_quality=PREVIEW_STANDARD)
        self.assertEqual(self.window.settings.preview_quality, PREVIEW_STANDARD)
        self.assertEqual(self.window.gallery.grid.preview_edge, THUMBNAIL_EDGE)
        self.assertEqual(self.window.viewer.preview_edge, THUMBNAIL_EDGE)
        saving.assert_called_once()  # the previews already saved are the other size

    def test_opening_the_video_library_from_settings(self):
        def exec_dialog(dialog):
            dialog.open_videos.click()
            return 0  # the dialog closes itself

        with patch.object(PreferencesDialog, "exec", exec_dialog), patch.object(self.window, "_start_cache_job"):
            self.window.show_preferences()
        self.assertIs(self.window.stack.currentWidget(), self.window.videos)

    def test_zooming_the_gallery_is_remembered(self):
        self.window.gallery.grid.zoom_in()
        zoomed = self.window.gallery.grid.tile_size
        self.assertGreater(zoomed, DEFAULT_TILE)
        self.assertEqual(self.window.settings.tile_size, zoomed)
        self.assertEqual(SettingsStore().load().tile_size, zoomed)


if __name__ == "__main__":
    unittest.main()
