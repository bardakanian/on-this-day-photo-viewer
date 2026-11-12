"""Regressions for the window stalls the stall log caught: theme re-application and per-card path lookups."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from onthisday.core.models import MediaRecord
from onthisday.ui.theme.manager import ThemeManager
from onthisday.ui.widgets.common import SearchBox
from onthisday.ui.widgets.gallery_grid import GalleryGrid

APP = QApplication.instance() or QApplication([])


class ThemeManagerTests(unittest.TestCase):
    def manager(self, preference: str, system_dark: bool = False) -> tuple[ThemeManager, list[str]]:
        applied: list[str] = []
        patcher = patch.object(APP, "setStyleSheet", side_effect=applied.append, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        patch_dark = patch.object(ThemeManager, "_system_is_dark", return_value=system_dark)
        self.dark = patch_dark.start()
        self.addCleanup(patch_dark.stop)
        manager = ThemeManager(APP, preference)
        self.addCleanup(self.disconnect, manager)
        return manager, applied

    @staticmethod
    def disconnect(manager: ThemeManager) -> None:
        for signal in (APP.styleHints().colorSchemeChanged, APP.paletteChanged):
            try:
                signal.disconnect(manager._system_changed)
            except (RuntimeError, TypeError):
                pass

    def test_the_stylesheet_is_applied_once_at_start(self):
        _, applied = self.manager("light")
        self.assertEqual(len(applied), 1)

    def test_saving_the_same_theme_again_does_not_restyle(self):
        manager, applied = self.manager("dark")
        changed = []
        manager.changed.connect(changed.append)
        manager.apply("dark")
        self.assertEqual((len(applied), changed), (1, []))

    def test_choosing_another_theme_restyles_once_and_announces_it(self):
        manager, applied = self.manager("light")
        changed = []
        manager.changed.connect(changed.append)
        manager.apply("dark")
        self.assertEqual((len(applied), changed), (2, ["dark"]))
        self.assertEqual(manager.resolved, "dark")

    def test_a_palette_change_event_does_not_restyle_the_app(self):
        # The original bug: every ApplicationPaletteChange rebuilt and re-applied the stylesheet.
        _, applied = self.manager("system")
        APP.sendEvent(APP, QEvent(QEvent.Type.ApplicationPaletteChange))
        APP.processEvents()
        self.assertEqual(len(applied), 1)

    def test_a_palette_signal_within_the_same_theme_does_not_restyle(self):
        manager, applied = self.manager("system", system_dark=False)
        manager._system_changed()
        manager._system_changed()
        self.assertEqual(len(applied), 1)

    def test_the_system_switching_to_dark_restyles_once(self):
        manager, applied = self.manager("system", system_dark=False)
        changed = []
        manager.changed.connect(changed.append)
        self.dark.return_value = True
        manager._system_changed()
        manager._system_changed()
        self.assertEqual((len(applied), changed, manager.resolved), (2, ["system"], "dark"))

    def test_a_fixed_theme_ignores_the_system(self):
        manager, applied = self.manager("light", system_dark=False)
        self.dark.return_value = True
        manager._system_changed()
        self.assertEqual((len(applied), manager.resolved), (1, "light"))


class SearchBoxTests(unittest.TestCase):
    def test_icon_is_rebuilt_only_when_its_colour_changes(self):
        box = SearchBox()
        self.addCleanup(box.deleteLater)
        with patch.object(box, "_search_icon", wraps=box._search_icon) as build:
            APP.sendEvent(box, QEvent(QEvent.Type.StyleChange))
            self.assertEqual(build.call_count, 0)
            palette = box.palette()
            palette.setColor(box.foregroundRole(), QColor("#ff0000"))
            box.setPalette(palette)
            self.assertGreaterEqual(build.call_count, 1)
        self.assertEqual(box._icon_color, QColor("#ff0000"))


class GalleryFolderTextTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.grid = GalleryGrid()
        self.addCleanup(self.grid.shutdown)
        self.grid.set_sections([], self.root)

    def record(self, *parts: str) -> MediaRecord:
        return MediaRecord(self.root.joinpath(*parts), datetime(2020, 5, 1, 12), "image", 1, 1)

    def test_folder_text_is_relative_to_the_library(self):
        self.assertEqual(self.grid._folder_text(self.record("photo.jpg")), "Library")
        self.assertEqual(self.grid._folder_text(self.record("trips", "photo.jpg")), str(Path("trips")))

    def test_a_file_outside_the_library_shows_its_own_folder(self):
        outside = MediaRecord(Path(self.root.anchor) / "elsewhere" / "a.jpg", datetime(2020, 5, 1), "image", 1, 1)
        self.assertEqual(self.grid._folder_text(outside), str(outside.path.parent))

    def test_drawing_cards_does_not_ask_the_file_system_for_the_library_path(self):
        records = [self.record(f"{n}.jpg") for n in range(50)]
        with patch.object(Path, "resolve", side_effect=AssertionError("resolve() called while drawing")):
            for record in records:
                self.grid._folder_text(record)

    def test_the_library_path_is_resolved_once_per_load(self):
        with patch.object(Path, "resolve", autospec=True, side_effect=lambda self_: self_) as resolve:
            self.grid.set_sections([], self.root)
            self.assertEqual(resolve.call_count, 1)

    def test_an_unreadable_library_path_does_not_break_drawing(self):
        with patch.object(Path, "resolve", side_effect=OSError("drive gone")):
            self.grid.set_sections([], self.root)
        self.assertEqual(self.grid._folder_text(self.record("a.jpg")), str(self.root))


if __name__ == "__main__":
    unittest.main()
