"""The gallery grid: layout arithmetic, and drawing and loading only what is on screen."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from onthisday.core.gallery_layout import (
    CARD_HEIGHT, CARD_WIDTH, HEADER_HEIGHT, SECTION_GAP, SPACING, columns_for, layout_sections,
)
from onthisday.core.models import MediaRecord
from onthisday.ui.pages.gallery_page import GalleryPage
from onthisday.ui.widgets.gallery_grid import PREVIEW

APP = QApplication.instance() or QApplication([])


class LayoutTests(unittest.TestCase):
    def test_columns(self):
        self.assertEqual(columns_for(0), 1)
        self.assertEqual(columns_for(CARD_WIDTH), 1)
        self.assertEqual(columns_for(3 * CARD_WIDTH + 2 * SPACING), 3)
        self.assertEqual(columns_for(3 * CARD_WIDTH + 2 * SPACING - 1), 2)

    def test_sections_rows_and_collapse(self):
        width = 3 * CARD_WIDTH + 2 * SPACING
        layout = layout_sections([7, 2], [False, False], width)
        headers = [cell for cell in layout.cells if cell.is_header]
        cards = [cell for cell in layout.cells if not cell.is_header]
        self.assertEqual(len(headers), 2)
        self.assertEqual(len(cards), 9)
        first_card = cards[0]
        self.assertEqual((first_card.x, first_card.y), (0, HEADER_HEIGHT + SPACING // 2))
        self.assertEqual(cards[3].y, first_card.y + CARD_HEIGHT + SPACING)  # 4th card starts row 2
        rows_end = first_card.y + 3 * CARD_HEIGHT + 2 * SPACING
        self.assertEqual(headers[1].y, rows_end + SECTION_GAP)

        collapsed = layout_sections([7, 2], [True, False], width)
        self.assertEqual(sum(not cell.is_header for cell in collapsed.cells), 2)
        self.assertLess(collapsed.height, layout.height)

    def test_visible_cells_match_a_full_search(self):
        layout = layout_sections([500, 40, 3], [False, True, False], 1100)
        for top in (0, 290, 5000, layout.height - 300):
            bottom = top + 700
            expected = [cell for cell in layout.cells if cell.y < bottom and cell.bottom > top]
            self.assertEqual(layout.visible(top, bottom), expected, top)

    def test_cell_at(self):
        layout = layout_sections([4], [False], 2 * CARD_WIDTH + SPACING)
        card = layout.cell_at(CARD_WIDTH + SPACING + 5, HEADER_HEIGHT + SPACING // 2 + 5)
        self.assertEqual((card.section, card.item), (0, 1))
        self.assertIsNone(layout.cell_at(CARD_WIDTH + 2, HEADER_HEIGHT + SPACING // 2 + 5))  # the gap


def records(year: int, count: int) -> list[MediaRecord]:
    return [MediaRecord(Path(f"/library/{year}/{index:04}.jpg"), datetime(year, 5, 1, 12), "image", 1, index)
            for index in range(count)]


class GridTests(unittest.TestCase):
    def setUp(self):
        self.page = GalleryPage()
        self.page.resize(1200, 800)
        self.page.show()
        APP.processEvents()  # lay the page out at its size
        self.requested = []
        self.patch = patch.object(self.page.grid.loader, "request",
                                  side_effect=lambda record, size, **_options: self.requested.append(record))
        self.patch.start()
        self.page.show_records(records(2024, 2000) + records(2019, 3), date(2026, 5, 1), "All", Path("/library"))
        self.grid = self.page.grid
        self.paint()

    def tearDown(self):
        self.patch.stop()
        self.page.shutdown()
        self.page.close()

    def paint(self) -> None:
        self.grid.viewport().repaint()
        APP.processEvents()

    def click(self, x: float, y: float, button=Qt.MouseButton.LeftButton) -> None:
        position = QPointF(x, y)
        for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            event = QMouseEvent(kind, position, self.grid.viewport().mapToGlobal(position), button, button,
                                Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(self.grid.viewport(), event)

    def test_only_cards_near_the_screen_load_thumbnails(self):
        self.assertEqual(len(self.page.records), 2003)
        self.assertGreater(len(self.requested), 0)
        self.assertLess(len(self.requested), 80, "thousands of cards would mean thumbnails for everything")
        self.grid.verticalScrollBar().setValue(self.grid.verticalScrollBar().maximum() // 2)
        self.paint()
        middle = [record.path.name for record in self.requested[-5:]]
        self.assertTrue(all("2024" in str(record.path) for record in self.requested))
        self.assertNotIn("0000.jpg", middle)

    def test_clicking_a_preview_opens_it(self):
        opened = []
        self.grid.open_requested.connect(opened.append)
        first = next(cell for cell in self.grid.layout_.cells if not cell.is_header)
        self.click(first.x + PREVIEW.center().x(), first.y + PREVIEW.center().y())
        self.assertEqual(opened, [self.page.records[0]])

    def test_trash_button_asks_to_delete(self):
        deleted = []
        self.grid.delete_requested.connect(deleted.append)
        second = [cell for cell in self.grid.layout_.cells if not cell.is_header][1]
        trash = self.grid._trash_rect(second).center()
        self.click(trash.x(), trash.y())
        self.assertEqual(deleted, [self.page.records[1]])

    def test_header_collapses_and_refresh_keeps_collapse_and_scroll(self):
        header = self.grid.layout_.cells[0]
        self.click(header.x + 20, header.y + header.height / 2)
        self.assertEqual(self.grid.collapsed, {2024})
        self.click(header.x + 20, header.y + header.height / 2)
        self.assertEqual(self.grid.collapsed, set())
        self.grid.verticalScrollBar().setValue(5000)
        self.page.show_records(records(2024, 1999) + records(2019, 3), date(2026, 5, 1), "All", Path("/library"))
        self.assertEqual(self.grid.verticalScrollBar().value(), 5000)  # one deleted, same place
        self.page.show_records(records(2024, 10), date(2026, 5, 2), "All", Path("/library"))
        self.assertEqual(self.grid.verticalScrollBar().value(), 0)  # a different day starts at the top

    def test_empty_day_shows_a_message(self):
        self.page.show_records([], date(2026, 5, 3), "Photos", Path("/library"))
        self.assertEqual(self.page.results.currentIndex(), 1)
        self.assertEqual(self.page.empty.title_label.text(), "No photos for May 3")
        self.assertFalse(self.page.empty.button.isVisibleTo(self.page.empty))


if __name__ == "__main__":
    unittest.main()
