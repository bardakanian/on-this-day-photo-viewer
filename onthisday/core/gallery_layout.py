"""Where the gallery's year headers and cards go, for a given width. Kept free of Qt so it can be tested.

The gallery draws only the cells that intersect the visible area, so a day with thousands of
items scrolls as smoothly as a day with ten.
"""

from bisect import bisect_right
from dataclasses import dataclass

CARD_WIDTH = 264
CARD_HEIGHT = 284
HEADER_HEIGHT = 40
SPACING = 16          # between cards, and between a header and its cards
SECTION_GAP = 22      # between one year's last row and the next year's header
BOTTOM_MARGIN = 24


@dataclass(frozen=True, slots=True)
class Cell:
    section: int
    item: int  # index within the section, or -1 for the section's header
    x: int
    y: int
    width: int
    height: int

    @property
    def is_header(self) -> bool:
        return self.item < 0

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x < self.x + self.width and self.y <= y < self.y + self.height


@dataclass(frozen=True, slots=True)
class GalleryLayout:
    cells: tuple[Cell, ...]   # in reading order; y never decreases
    height: int
    columns: int
    bottoms: tuple[int, ...]  # each cell's bottom edge; non-decreasing, so it can be bisected

    def visible(self, top: float, bottom: float) -> list[Cell]:
        """Cells that overlap the band from `top` to `bottom`."""
        start = bisect_right(self.bottoms, top)
        result = []
        for index in range(start, len(self.cells)):
            cell = self.cells[index]
            if cell.y >= bottom:
                break
            result.append(cell)
        return result

    def cell_at(self, x: float, y: float) -> Cell | None:
        for cell in self.visible(y, y + 1):
            if cell.contains(x, y):
                return cell
        return None


def columns_for(width: int) -> int:
    return max(1, (width + SPACING) // (CARD_WIDTH + SPACING))


def layout_sections(counts: list[int], collapsed: list[bool], width: int) -> GalleryLayout:
    """Lay out one header per section followed by its cards in rows (none when collapsed)."""
    columns = columns_for(width)
    cells: list[Cell] = []
    y = 0
    for section, (count, is_collapsed) in enumerate(zip(counts, collapsed)):
        if section:
            y += SECTION_GAP
        cells.append(Cell(section, -1, 0, y, max(width, CARD_WIDTH), HEADER_HEIGHT))
        y += HEADER_HEIGHT
        if is_collapsed or not count:
            continue
        y += SPACING // 2
        for item in range(count):
            row, column = divmod(item, columns)
            cells.append(Cell(section, item, column * (CARD_WIDTH + SPACING), y + row * (CARD_HEIGHT + SPACING),
                              CARD_WIDTH, CARD_HEIGHT))
        rows = (count + columns - 1) // columns
        y += rows * CARD_HEIGHT + (rows - 1) * SPACING
    return GalleryLayout(tuple(cells), y + BOTTOM_MARGIN if cells else 0, columns, tuple(cell.bottom for cell in cells))
