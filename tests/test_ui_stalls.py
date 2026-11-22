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


class GalleryPaintTests(unittest.TestCase):
    """Drawing tiles must not touch the file system: on Windows that cost a third of a second a redraw."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.grid = GalleryGrid()
        self.addCleanup(self.grid.shutdown)
        self.grid.resize(900, 700)
        self.grid.set_sections([(2024, self.records(60))], self.root)

    def records(self, count: int) -> list[MediaRecord]:
        return [MediaRecord(self.root / f"{index}.jpg", datetime(2024, 5, 1, 12), "image", 1, index)
                for index in range(count)]

    def test_drawing_does_not_ask_the_file_system(self):
        with patch.object(self.grid.loader, "request"):  # loading files is the loader's job, off the UI thread
            self.grid.viewport().repaint()  # paints, and asks for the previews it needs
            for attribute in ("resolve", "exists", "stat"):
                with patch.object(Path, attribute, side_effect=AssertionError(f"{attribute}() called while drawing")):
                    self.grid.viewport().repaint()


if __name__ == "__main__":
    unittest.main()
