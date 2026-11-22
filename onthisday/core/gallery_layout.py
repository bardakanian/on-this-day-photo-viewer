"""Where the gallery's year headings and tiles go, for a given width. Kept free of Qt so it can be tested.

Tiles are square and stretch so each row fills the width exactly, like Photos: the picture is
cropped to the tile rather than padded, so the grid has no gaps. The gallery draws only the cells
that intersect the visible area, so a day with thousands of items scrolls as smoothly as one with ten.
"""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass

# Tile size in points, changed by zooming (Settings remembers it).
DEFAULT_TILE = 170
MIN_TILE = 90
MAX_TILE = 420
ZOOM_STEP = 1.25

SPACING = 2           # between tiles, as in Photos: just enough to tell them apart
MARGIN = 14           # left and right of the grid
HEADER_HEIGHT = 46
SECTION_GAP = 10      # between one year's last row and the next year's heading
BOTTOM_MARGIN = 24


@dataclass(frozen=True, slots=True)
class Cell:
    section: int
    item: int  # index within the section, or -1 for the section's heading
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
    headers: tuple[Cell, ...] = ()  # one per section, top to bottom
    tile: int = DEFAULT_TILE  # the drawn tile size, which stretches to fill the width

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

    def pinned_header(self, top: float) -> Cell | None:
        """The heading to keep at the top of the screen while its year scrolls past, if any.

        It's the heading of the section showing at `top`, once that heading has scrolled out of
        view, placed at `top`, except that the next section's heading pushes it up as it arrives.
        Positions are in content coordinates, like every other cell's.
        """
        headers = self.headers
        current = bisect_left([header.y for header in headers], top) - 1  # the last one above `top`
        if current < 0:
            return None
        header = headers[current]
        y = top
        if current + 1 < len(headers):
            y = min(y, headers[current + 1].y - header.height)
        if y <= header.y or y + header.height <= top:
            return None  # the real heading is still where it belongs, or the next one has pushed it off
        return Cell(header.section, -1, header.x, int(y), header.width, header.height)

    def cell_at(self, x: float, y: float) -> Cell | None:
        for cell in self.visible(y, y + 1):
            if cell.contains(x, y):
                return cell
        return None


def columns_for(width: int, tile: int = DEFAULT_TILE) -> int:
    available = max(1, width - 2 * MARGIN)
    return max(1, (available + SPACING) // (max(1, tile) + SPACING))


def layout_sections(counts: list[int], collapsed: list[bool], width: int,
                    tile: int = DEFAULT_TILE) -> GalleryLayout:
    """Lay out one heading per section followed by its tiles in rows (none when collapsed)."""
    columns = columns_for(width, tile)
    available = max(1, width - 2 * MARGIN)
    # Stretch the tiles so each row fills the width exactly; rounding edges rather than sizes
    # keeps neighbours from overlapping or leaving a gap.
    exact = max(1.0, (available - (columns - 1) * SPACING) / columns)
    cells: list[Cell] = []
    y = 0
    for section, (count, is_collapsed) in enumerate(zip(counts, collapsed)):
        if section:
            y += SECTION_GAP
        cells.append(Cell(section, -1, 0, y, max(width, 1), HEADER_HEIGHT))
        y += HEADER_HEIGHT
        if is_collapsed or not count:
            continue
        rows = (count + columns - 1) // columns
        for item in range(count):
            row, column = divmod(item, columns)
            left = MARGIN + column * (exact + SPACING)
            top = y + row * (exact + SPACING)
            x, cell_y = round(left), round(top)
            cells.append(Cell(section, item, x, cell_y, round(left + exact) - x, round(top + exact) - cell_y))
        y = round(y + rows * (exact + SPACING) - SPACING)
    return GalleryLayout(tuple(cells), y + BOTTOM_MARGIN if cells else 0, columns,
                         tuple(cell.bottom for cell in cells),
                         tuple(cell for cell in cells if cell.is_header), round(exact))
