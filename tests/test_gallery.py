"""The gallery grid: layout arithmetic, and drawing and loading only what is on screen."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from onthisday.core.constants import HIGH_THUMBNAIL_EDGE, THUMBNAIL_EDGE
from onthisday.core.gallery_layout import (
    DEFAULT_TILE, HEADER_HEIGHT, MARGIN, MAX_TILE, MIN_TILE, SECTION_GAP, SPACING, columns_for, layout_sections,
)
from onthisday.core.models import MediaRecord
from onthisday.ui.pages.gallery_page import GalleryPage
from tests.test_auto_refresh import WindowTestCase

APP = QApplication.instance() or QApplication([])

ONE_COLUMN = 2 * MARGIN + DEFAULT_TILE


class LayoutTests(unittest.TestCase):
    def test_columns(self):
        self.assertEqual(columns_for(0), 1)
        self.assertEqual(columns_for(ONE_COLUMN), 1)
        self.assertEqual(columns_for(2 * MARGIN + 3 * DEFAULT_TILE + 2 * SPACING), 3)
        self.assertEqual(columns_for(2 * MARGIN + 3 * DEFAULT_TILE + 2 * SPACING - 1), 2)
        self.assertEqual(columns_for(1000, tile=MIN_TILE), 10)  # zoomed out: more, smaller tiles

    def test_tiles_are_square_and_fill_each_row(self):
        width = 1000
        layout = layout_sections([7, 2], [False, False], width)
        tiles = [cell for cell in layout.cells if not cell.is_header]
        self.assertEqual(len(tiles), 9)
        for tile in tiles:
            # Edges are rounded, not sizes, so a tile can be a pixel off square; a row is uniform.
            self.assertAlmostEqual(tile.width, tile.height, delta=1)
        self.assertEqual(len({tile.height for tile in tiles}), 1)
        row = [tile for tile in tiles if tile.y == tiles[0].y]
        self.assertEqual(len(row), layout.columns)
        self.assertEqual(row[0].x, MARGIN)
        self.assertEqual(row[-1].x + row[-1].width, width - MARGIN)  # the row fills the width exactly
        self.assertEqual({b.x - (a.x + a.width) for a, b in zip(row, row[1:])}, {SPACING})

    def test_sections_rows_and_collapse(self):
        layout = layout_sections([7, 2], [False, False], 1000)
        headers = [cell for cell in layout.cells if cell.is_header]
        tiles = [cell for cell in layout.cells if not cell.is_header]
        self.assertEqual(len(headers), 2)
        self.assertEqual(headers[0].y, 0)
        self.assertEqual(tiles[0].y, HEADER_HEIGHT)
        second_row = tiles[layout.columns]
        self.assertEqual(second_row.y, tiles[0].y + tiles[0].height + SPACING)
        self.assertEqual(headers[1].y, second_row.bottom + SECTION_GAP)

        collapsed = layout_sections([7, 2], [True, False], 1000)
        self.assertEqual(sum(not cell.is_header for cell in collapsed.cells), 2)
        self.assertLess(collapsed.height, layout.height)

    def test_visible_cells_match_a_full_search(self):
        layout = layout_sections([500, 40, 3], [False, True, False], 1100)
        for top in (0, 290, 5000, layout.height - 300):
            bottom = top + 700
            expected = [cell for cell in layout.cells if cell.y < bottom and cell.bottom > top]
            self.assertEqual(layout.visible(top, bottom), expected, top)

    def test_cell_at(self):
        layout = layout_sections([4], [False], 2 * MARGIN + 2 * DEFAULT_TILE + SPACING)
        second = [cell for cell in layout.cells if not cell.is_header][1]
        self.assertEqual(layout.cell_at(second.x + 5, second.y + 5).item, 1)
        self.assertIsNone(layout.cell_at(second.x - 1, second.y + 5))  # the gap between tiles


def records(year: int, count: int, media_type: str = "image") -> list[MediaRecord]:
    return [MediaRecord(Path(f"/library/{year}/{index:04}.jpg"), datetime(year, 5, 1, 12), media_type, 1, index)
            for index in range(count)]


class PinnedHeaderTests(unittest.TestCase):
    """The year scrolling past stays at the top of the screen."""

    def setUp(self):
        self.layout = layout_sections([20, 20], [False, False], ONE_COLUMN)
        self.first, self.second = self.layout.headers

    def test_nothing_pinned_while_the_header_is_in_view(self):
        self.assertIsNone(self.layout.pinned_header(0))

    def test_header_follows_the_top_of_the_screen(self):
        pinned = self.layout.pinned_header(1000)
        self.assertEqual((pinned.section, pinned.y), (0, 1000))
        self.assertTrue(pinned.is_header)

    def test_next_header_pushes_it_up_then_takes_over(self):
        top = self.second.y - HEADER_HEIGHT // 2  # the next header is half way up the pinned one
        self.assertEqual(self.layout.pinned_header(top).y, self.second.y - HEADER_HEIGHT)
        self.assertIsNone(self.layout.pinned_header(self.second.y))  # its own header is at the top
        self.assertEqual(self.layout.pinned_header(self.second.y + 1).section, 1)


class GridTests(unittest.TestCase):
    def setUp(self):
        self.page = GalleryPage()
        self.page.resize(1200, 800)
        self.page.show()
        APP.processEvents()  # lay the page out at its size
        self.requested = []
        self.patch = patch.object(self.page.grid.loader, "request",
                                  side_effect=lambda record, size, *args, **options:
                                  self.requested.append((record, size)))
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

    def tiles(self) -> list:
        return [cell for cell in self.grid.layout_.cells if not cell.is_header]

    def click(self, x: float, y: float, button=Qt.MouseButton.LeftButton) -> None:
        position = QPointF(x, y)
        for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            event = QMouseEvent(kind, position, self.grid.viewport().mapToGlobal(position), button, button,
                                Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(self.grid.viewport(), event)

    def test_only_tiles_near_the_screen_load_previews(self):
        self.assertEqual(len(self.page.records), 2003)
        self.assertGreater(len(self.requested), 0)
        self.assertLess(len(self.requested), 150, "thousands of tiles would mean previews for everything")
        self.grid.verticalScrollBar().setValue(self.grid.verticalScrollBar().maximum() // 2)
        self.paint()
        self.assertTrue(all("2024" in str(record.path) for record, _ in self.requested))
        self.assertNotIn("0000.jpg", [record.path.name for record, _ in self.requested[-5:]])

    def test_previews_are_asked_for_at_the_tile_size(self):
        self.grid.clear_thumbnails()  # nothing loaded or in flight
        self.requested.clear()
        self.paint()
        ratio = self.grid.devicePixelRatioF()
        wanted = round(self.grid.layout_.tile * ratio)
        self.assertEqual({size.width() for _, size in self.requested}, {wanted})
        self.assertEqual({size.height() for _, size in self.requested}, {wanted})

    def test_clicking_a_tile_opens_it(self):
        opened = []
        self.grid.open_requested.connect(opened.append)
        first = self.tiles()[0]
        self.click(first.x + first.width / 2, first.y + first.height / 2)
        self.assertEqual(opened, [self.page.records[0]])

    def test_right_click_offers_open_and_trash(self):
        deleted = []
        self.grid.delete_requested.connect(deleted.append)
        menu = self.grid.context_menu(self.page.records[1])
        trash = [action for action in menu.actions() if action.text() == "Move to Trash"]
        self.assertEqual(len(trash), 1)
        self.assertTrue(trash[0].isEnabled())
        trash[0].trigger()
        self.assertEqual(deleted, [self.page.records[1]])

    def test_read_only_drive_disables_trash(self):
        self.page.show_records(records(2024, 10), date(2026, 5, 1), "All", Path("/library"), read_only=True)
        menu = self.grid.context_menu(self.page.records[0])
        trash = next(action for action in menu.actions() if action.text() == "Move to Trash")
        self.assertFalse(trash.isEnabled())

    def test_offline_offers_no_trash_at_all(self):
        self.page.show_records(records(2024, 10), date(2026, 5, 1), "All", Path("/library"), offline=True)
        menu = self.grid.context_menu(self.page.records[0])
        self.assertEqual([action.text() for action in menu.actions() if action.text()], ["Open"])

    def test_zooming_changes_the_tile_size_and_reports_it(self):
        sizes = []
        self.grid.tile_size_changed.connect(sizes.append)
        before = self.grid.layout_.tile
        self.grid.zoom_in()
        self.paint()
        self.assertGreater(self.grid.layout_.tile, before)
        self.assertEqual(sizes[-1], self.grid.tile_size)
        self.grid.set_tile_size(10_000)
        self.assertEqual(self.grid.tile_size, MAX_TILE)
        self.grid.set_tile_size(1)
        self.assertEqual(self.grid.tile_size, MIN_TILE)
        self.grid.reset_zoom()
        self.assertEqual(self.grid.tile_size, DEFAULT_TILE)

    def test_zooming_keeps_bigger_tiles_sharp(self):
        self.requested.clear()
        self.grid.zoom_in()
        self.paint()
        ratio = self.grid.devicePixelRatioF()
        self.assertEqual({size.width() for _, size in self.requested}, {round(self.grid.layout_.tile * ratio)})

    def test_changing_preview_quality_reloads_the_tiles(self):
        self.grid.set_preview_quality(HIGH_THUMBNAIL_EDGE)
        self.requested.clear()
        self.paint()
        self.assertGreater(len(self.requested), 0)
        self.assertEqual(self.grid.preview_edge, HIGH_THUMBNAIL_EDGE)
        self.grid.set_preview_quality(THUMBNAIL_EDGE)
        self.assertEqual(self.grid.preview_edge, THUMBNAIL_EDGE)

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

    def test_pinned_header_collapses_its_year_without_scrolling_up(self):
        self.grid.verticalScrollBar().setValue(5000)  # deep inside 2024
        self.paint()
        self.click(MARGIN + 20, HEADER_HEIGHT / 2)  # the top of the screen: 2024's pinned header, not a tile
        self.assertEqual(self.grid.collapsed, {2024})
        self.assertEqual(self.grid.verticalScrollBar().value(), 0)  # its header is back at the top
        self.paint()
        self.click(MARGIN + 20, HEADER_HEIGHT / 2)  # and it can be expanded again from there
        self.assertEqual(self.grid.collapsed, set())

    def test_empty_day_shows_a_message(self):
        self.page.show_records([], date(2026, 5, 3), "Photos", Path("/library"))
        self.assertEqual(self.page.results.currentIndex(), 1)
        self.assertEqual(self.page.empty.title_label.text(), "No photos for May 3")
        self.assertFalse(self.page.empty.button.isVisibleTo(self.page.empty))


class TileShortcutTests(WindowTestCase):
    """The tile-size keys are the viewer's photo-zoom keys, so only one owns them at a time."""

    def enabled(self) -> list[bool]:
        return [action.isEnabled() for action in self.window.tile_actions]

    def test_the_viewer_keeps_the_zoom_keys_while_it_is_open(self):
        self.assertEqual(self.enabled(), [True] * 3)  # the gallery is showing
        self.window.stack.setCurrentWidget(self.window.viewer)
        self.assertEqual(self.enabled(), [False] * 3, "both would swallow the shortcut, so neither acts")
        self.window.stack.setCurrentWidget(self.window.gallery)
        self.assertEqual(self.enabled(), [True] * 3)

    def test_the_menu_actions_resize_tiles(self):
        larger, smaller, default = self.window.tile_actions
        before = self.window.gallery.grid.tile_size
        larger.trigger()
        self.assertGreater(self.window.gallery.grid.tile_size, before)
        smaller.trigger()
        self.assertEqual(self.window.gallery.grid.tile_size, before)
        larger.trigger()
        default.trigger()
        self.assertEqual(self.window.gallery.grid.tile_size, DEFAULT_TILE)


if __name__ == "__main__":
    unittest.main()
