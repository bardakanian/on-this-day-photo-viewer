from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, Signal, Slot
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractScrollArea, QMenu, QToolTip

from ...core.constants import THUMBNAIL_EDGE
from ...core.gallery_layout import (
    DEFAULT_TILE, MARGIN, MAX_TILE, MIN_TILE, ZOOM_STEP, Cell, GalleryLayout, layout_sections,
)
from ...core.media import get_cached_thumbnail, other_thumbnail_edge, read_only_trash_reason, thumbnail_cache_path
from ...core.models import MediaRecord
from ...core.timeformat import DEFAULT_TIME_FORMAT, format_capture
from ...core.workqueue import WorkQueue
from ..theme.colors import LIGHT, Palette
from ..theme.metrics import Metrics
from ..theme.typography import Typography

# Decoded tiles are held in memory; a screenful is 20 to 40, and the budget covers several screens.
PIXMAP_CACHE_BYTES = 192 * 1024 * 1024
TRASH_LABEL = "Move to Trash"
FAILED = object()  # the preview could not be made


def _thumbnail_key(record: MediaRecord) -> tuple:
    return str(record.path), record.file_size, record.modified_ns


def _load_filling(path: Path | None, size: QSize) -> QImage | None:
    """Decode a saved preview scaled to fill a square tile (the overflow is cropped when drawn).

    QImage is safe to use off the UI thread; QPixmap is not.
    """
    if path is None:
        return None
    image = QImage(str(path))
    if image.isNull():
        return None
    return image.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)


def _fill_source(pixmap: QPixmap, target: QRectF) -> QRectF:
    """The centred part of the pixmap with the tile's shape, so the picture fills it without stretching."""
    ratio = target.width() / max(1.0, target.height())
    width, height = pixmap.width(), pixmap.height()
    if width / max(1, height) > ratio:
        cropped = height * ratio
        return QRectF((width - cropped) / 2, 0, cropped, height)
    cropped = width / ratio
    return QRectF(0, (height - cropped) / 2, width, cropped)


class _Signals(QObject):
    loaded = Signal(object, object, int, bool)  # key, QImage or None, pixel size, final


class ThumbnailLoader(QObject):
    """Loads gallery previews in the background, emitting `loaded(key, image, size, final)` on the UI thread.

    A saved preview is read on one queue; making a missing one (slow for videos) runs on
    another, so reading never waits behind ffmpeg. Both drop work scrolled out of view.
    """

    loaded = Signal(object, object, int, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._read = WorkQueue(4, "thumbnail-read")
        self._generate = WorkQueue(3, "thumbnail-generate")
        self._signals = _Signals()
        self._signals.loaded.connect(self.loaded)

    def request(self, record: MediaRecord, size: QSize, edge: int = THUMBNAIL_EDGE,
                generate_missing: bool = True) -> None:
        """Load a saved preview, making it first when it's missing (unless `generate_missing` is off,
        as while the originals' drive is disconnected)."""
        key = _thumbnail_key(record)
        emit = self._emit
        pixels = max(size.width(), size.height())

        def generate():
            result = get_cached_thumbnail(record.path, record.media_type, record.file_size,
                                          record.modified_ns, edge)
            emit(key, _load_filling(result, size), pixels, True)

        def read():
            saved = thumbnail_cache_path(record.path, record.file_size, record.modified_ns, edge)
            if saved.exists():
                emit(key, _load_filling(saved, size), pixels, True)
                return
            # The other quality's preview stands in while this one is being made.
            spare = thumbnail_cache_path(record.path, record.file_size, record.modified_ns,
                                         other_thumbnail_edge(edge))
            if not generate_missing:
                emit(key, _load_filling(spare, size) if spare.exists() else None, pixels, True)
                return
            if spare.exists():
                emit(key, _load_filling(spare, size), pixels, False)
            self._generate.submit(key, generate)

        self._read.submit(key, read)

    def focus(self, keys: list[tuple]) -> list[tuple]:
        """Drop queued work for anything but `keys` (nearest first); returns the dropped keys."""
        return self._read.retain(keys) + self._generate.retain(keys)

    def clear(self) -> None:
        self._read.clear()
        self._generate.clear()

    def shutdown(self) -> None:
        self._read.shutdown()
        self._generate.shutdown()

    def _emit(self, key: tuple, image: QImage | None, pixels: int, final: bool) -> None:
        try:
            self._signals.loaded.emit(key, image, pixels, final)
        except RuntimeError:
            pass  # the window closed while loading


class GalleryGrid(QAbstractScrollArea):
    """The gallery's year headings and square tiles, drawn rather than built from widgets.

    Only the tiles on screen are painted and have previews loaded, so very large days stay fast.
    """

    open_requested = Signal(object)    # MediaRecord
    delete_requested = Signal(object)  # MediaRecord
    tile_size_changed = Signal(int)    # after zooming, so the size can be remembered

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QAbstractScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Photos and videos")
        self.viewport().setMouseTracking(True)
        self.verticalScrollBar().setSingleStep(48)
        self.colors: Palette = LIGHT
        self.time_format = DEFAULT_TIME_FORMAT
        self.root_folder: Path | None = None
        self.tile_size = DEFAULT_TILE
        self.preview_edge = THUMBNAIL_EDGE
        self.offline = False  # the originals' drive is disconnected: saved previews only, no Trash
        self.read_only = False  # the originals' drive can't be changed: nothing can be moved to the Trash
        self.sections: list[tuple[int, list[MediaRecord]]] = []
        self.collapsed: set[int] = set()
        self.layout_: GalleryLayout = layout_sections([], [], 0)
        self.loader = ThumbnailLoader(self)
        self.loader.loaded.connect(self._thumbnail_loaded)
        self._pixmaps: OrderedDict[tuple, QPixmap | object] = OrderedDict()
        self._pixmap_pixels: dict[tuple, int] = {}  # the size each was decoded at, for zooming
        self._cached_bytes = 0
        self._requested: set[tuple] = set()
        self._hover: Cell | None = None
        self._pressed: tuple[Cell, str] | None = None
        self._caption_font = QFont()
        self._caption_font.setPixelSize(Typography.CAPTION)
        self._body_font = QFont()
        self._body_font.setPixelSize(Typography.BODY)
        self._header_font = QFont()
        self._header_font.setPixelSize(Typography.SECTION)
        self._header_font.setWeight(QFont.Weight.DemiBold)
        self._badge_font = QFont(self._caption_font)
        self._badge_font.setWeight(QFont.Weight.DemiBold)

    # Content -------------------------------------------------------------------

    def set_sections(self, sections: list[tuple[int, list[MediaRecord]]], root_folder: Path | None,
                     collapsed: set[int] | None = None, offline: bool = False, read_only: bool = False) -> None:
        self.read_only = read_only
        if offline != self.offline:
            # Previews looked up in the other mode may be wrong now: missing ones can be made
            # once the drive is back, and ones made before it went away can be shown.
            self.clear_thumbnails()
        self.offline = offline
        self.sections = sections
        self.root_folder = root_folder
        self.collapsed = {year for year in (collapsed or set()) if any(year == y for y, _ in sections)}
        self._hover = self._pressed = None
        self._relayout()

    def set_colors(self, colors: Palette) -> None:
        self.colors = colors
        self.viewport().update()

    def set_time_format(self, time_format: str) -> None:
        self.time_format = time_format
        self.viewport().update()

    def set_preview_quality(self, edge: int) -> None:
        if edge == self.preview_edge:
            return
        self.preview_edge = edge
        self.clear_thumbnails()  # the tiles on screen reload at the new quality
        self.viewport().update()

    def set_tile_size(self, size: int, anchor: QPointF | None = None) -> int:
        """Resize the tiles, keeping whatever is under `anchor` (or the middle) in place."""
        size = max(MIN_TILE, min(MAX_TILE, int(size)))
        if size == self.tile_size:
            return size
        point = anchor if anchor is not None else QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
        held = self.layout_.cell_at(point.x(), point.y() + self._offset())
        self.tile_size = size
        self._relayout()
        if held is not None and not held.is_header:
            moved = next((cell for cell in self.layout_.cells
                          if cell.section == held.section and cell.item == held.item), None)
            if moved is not None:
                self.verticalScrollBar().setValue(round(moved.y - point.y()))
        self.tile_size_changed.emit(size)
        return size

    def zoom_in(self) -> None:
        self.set_tile_size(round(self.tile_size * ZOOM_STEP))

    def zoom_out(self) -> None:
        self.set_tile_size(round(self.tile_size / ZOOM_STEP))

    def reset_zoom(self) -> None:
        self.set_tile_size(DEFAULT_TILE)

    def toggle_section(self, year: int) -> None:
        self.collapsed ^= {year}
        header = next((cell for cell in self.layout_.cells
                       if cell.is_header and self.sections[cell.section][0] == year), None)
        self._relayout()
        # Toggled from the pinned heading: its year started above the screen. Bring its heading to the
        # top, so a collapse doesn't leave you somewhere in a later year (sections above don't move).
        if header is not None and header.y < self._offset():
            self.verticalScrollBar().setValue(header.y)

    def record_for(self, cell: Cell) -> MediaRecord | None:
        if cell.is_header or not 0 <= cell.section < len(self.sections):
            return None
        records = self.sections[cell.section][1]
        return records[cell.item] if cell.item < len(records) else None

    def shutdown(self) -> None:
        self.loader.shutdown()

    # Layout and scrolling ------------------------------------------------------

    def _relayout(self) -> None:
        width = max(2 * MARGIN + MIN_TILE, self.viewport().width())
        drawn_at = self.layout_.tile
        self.layout_ = layout_sections(
            [len(records) for _, records in self.sections],
            [year in self.collapsed for year, _ in self.sections],
            width, self.tile_size,
        )
        if self.layout_.tile != drawn_at:
            # Zoomed, or the window was resized: what is in flight is for the old tile size.
            self._requested.clear()
        bar = self.verticalScrollBar()
        bar.setPageStep(self.viewport().height())
        bar.setRange(0, max(0, self.layout_.height - self.viewport().height()))
        self.viewport().update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        self.viewport().update()

    def _offset(self) -> int:
        return self.verticalScrollBar().value()

    # Painting ------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        offset = self._offset()
        height = self.viewport().height()
        painter.translate(0, -offset)
        for cell in self.layout_.visible(offset, offset + height):
            if cell.is_header:
                self._paint_header(painter, cell)
            else:
                record = self.record_for(cell)
                if record is not None:
                    self._paint_tile(painter, cell, record)
        pinned = self.layout_.pinned_header(offset)
        if pinned is not None:
            # Over the tiles scrolling beneath it, so the year stays in view and can be collapsed.
            band = QRectF(0, pinned.y, self.viewport().width(), pinned.height)
            painter.fillRect(band, QColor(self.colors.background))
            painter.setPen(QColor(self.colors.border))
            painter.drawLine(band.bottomLeft(), band.bottomRight())
            self._paint_header(painter, pinned)
        painter.end()
        # Load what is on screen plus about a screen below, the likeliest next stop.
        self._request_thumbnails(self.layout_.visible(offset - height // 2, offset + 2 * height))

    def _paint_header(self, painter: QPainter, cell: Cell) -> None:
        year, records = self.sections[cell.section]
        c = self.colors
        painter.setFont(self._header_font)
        painter.setPen(QColor(c.text))
        arrow = "›" if year in self.collapsed else "▾"
        title = f"{arrow}  {year}"
        metrics = QFontMetrics(self._header_font)
        title_rect = QRectF(cell.x + MARGIN - 4, cell.y, metrics.horizontalAdvance(title) + 8, cell.height)
        if self._hover is not None and self._hover == cell:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c.surface_alt))
            painter.drawRoundedRect(title_rect.adjusted(-6, 7, 6, -7), Metrics.RADIUS_SMALL, Metrics.RADIUS_SMALL)
            painter.setPen(QColor(c.text))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, title)
        badge = f"{len(records):,} {'item' if len(records) == 1 else 'items'}"
        badge_metrics = QFontMetrics(self._badge_font)
        badge_rect = QRectF(title_rect.right() + 12, cell.y + (cell.height - 20) / 2,
                            badge_metrics.horizontalAdvance(badge) + 14, 20)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c.surface_alt))
        painter.drawRoundedRect(badge_rect, Metrics.RADIUS, Metrics.RADIUS)
        painter.setFont(self._badge_font)
        painter.setPen(QColor(c.text_muted))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge)

    def _paint_tile(self, painter: QPainter, cell: Cell, record: MediaRecord) -> None:
        c = self.colors
        rect = QRectF(cell.x, cell.y, cell.width, cell.height)
        pixmap = self._pixmaps.get(_thumbnail_key(record))
        painter.fillRect(rect, QColor(c.surface_alt))
        if isinstance(pixmap, QPixmap):
            painter.drawPixmap(rect, pixmap, _fill_source(pixmap, rect))
        elif pixmap is FAILED and cell.width >= 96:
            painter.setFont(self._caption_font)
            painter.setPen(QColor(c.text_subtle))
            text = "No saved preview" if self.offline else "No preview"
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        if record.is_live:
            self._paint_live_badge(painter, rect)
        elif record.is_video:
            self._paint_video_badge(painter, rect)
        if self._hover is not None and self._hover == cell:
            painter.setPen(QPen(QColor(c.accent), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1.5, 1.5, -1.5, -1.5))

    @staticmethod
    def _paint_live_badge(painter: QPainter, rect: QRectF) -> None:
        """The Live Photo mark, a dotted ring around a dot, in the tile's top-left corner."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre = QPointF(rect.left() + 16, rect.top() + 16)
        for colour, width in ((QColor(0, 0, 0, 90), 3.2), (QColor(255, 255, 255, 240), 1.6)):
            pen = QPen(colour, width)
            pen.setDashPattern([1.2, 1.4])
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(centre, 8.0, 8.0)
            painter.setPen(QPen(colour, width - 0.4))
            painter.drawEllipse(centre, 5.0, 5.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 240))
        painter.drawEllipse(centre, 2.2, 2.2)
        painter.restore()

    @staticmethod
    def _paint_video_badge(painter: QPainter, rect: QRectF) -> None:
        """A play mark in the tile's bottom-left corner, so videos stand out among the photos."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre = QPointF(rect.left() + 18, rect.bottom() - 18)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 110))
        painter.drawEllipse(centre, 11.0, 11.0)
        triangle = QPainterPath()
        triangle.moveTo(centre.x() - 3.4, centre.y() - 5.2)
        triangle.lineTo(centre.x() + 5.6, centre.y())
        triangle.lineTo(centre.x() - 3.4, centre.y() + 5.2)
        triangle.closeSubpath()
        painter.setBrush(QColor(255, 255, 255, 240))
        painter.drawPath(triangle)
        painter.restore()

    # Previews ------------------------------------------------------------------

    def _tile_pixels(self) -> QSize:
        edge = round(self.layout_.tile * self.devicePixelRatioF())
        return QSize(edge, edge)

    def _request_thumbnails(self, cells: list[Cell]) -> None:
        size = self._tile_pixels()
        needed = max(size.width(), size.height())
        wanted = []
        for cell in cells:
            record = self.record_for(cell)
            if record is None:
                continue
            key = _thumbnail_key(record)
            wanted.append(key)
            if key in self._pixmaps:
                self._pixmaps.move_to_end(key)  # keep what's on screen in the cache
            # Reload when the tiles have grown past what was decoded, so zooming in stays sharp.
            sharp_enough = self._pixmap_pixels.get(key, 0) >= needed * 0.95
            if key not in self._requested and not (key in self._pixmaps and sharp_enough):
                self._requested.add(key)
                self.loader.request(record, size, self.preview_edge, generate_missing=not self.offline)
        for key in self.loader.focus(wanted):
            self._requested.discard(key)  # scrolled away; asked for again when it comes back

    @Slot(object, object, int, bool)
    def _thumbnail_loaded(self, key: tuple, image: QImage | None, pixels: int, final: bool) -> None:
        if image is None:
            if final:
                self._requested.discard(key)
                if key not in self._pixmaps:
                    self._pixmaps[key] = FAILED
            return
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(self.devicePixelRatioF())
        self._store(key, pixmap, pixels)
        if final:
            self._requested.discard(key)
        self.viewport().update()

    def _store(self, key: tuple, pixmap: QPixmap, pixels: int) -> None:
        self._drop(key)
        self._pixmaps[key] = pixmap
        self._pixmap_pixels[key] = pixels
        self._cached_bytes += pixmap.width() * pixmap.height() * 4
        while self._cached_bytes > PIXMAP_CACHE_BYTES and len(self._pixmaps) > 1:
            self._drop(next(iter(self._pixmaps)))

    def _drop(self, key: tuple) -> None:
        existing = self._pixmaps.pop(key, None)
        self._pixmap_pixels.pop(key, None)
        if isinstance(existing, QPixmap):
            self._cached_bytes -= existing.width() * existing.height() * 4

    def clear_thumbnails(self) -> None:
        """Forget loaded previews (for example after the files on disk changed)."""
        self.loader.clear()
        self._pixmaps.clear()
        self._pixmap_pixels.clear()
        self._cached_bytes = 0
        self._requested.clear()

    # Interaction ---------------------------------------------------------------

    def _cell_at_position(self, position: QPointF) -> Cell | None:
        x, y = position.x(), position.y() + self._offset()
        pinned = self.layout_.pinned_header(self._offset())
        if pinned is not None and pinned.contains(x, y):
            return pinned
        return self.layout_.cell_at(x, y)

    def mouseMoveEvent(self, event) -> None:
        cell = self._cell_at_position(event.position())
        if cell != self._hover:
            self._hover = cell
            self.viewport().setCursor(QCursor(Qt.CursorShape.PointingHandCursor if cell is not None
                                              else Qt.CursorShape.ArrowCursor))
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover is not None:
            self._hover = None
            self.viewport().update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            cell = self._cell_at_position(event.position())
            self._pressed = (cell, "header" if cell is not None and cell.is_header else "tile") if cell else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        pressed, self._pressed = self._pressed, None
        released = self._cell_at_position(event.position())
        if event.button() != Qt.MouseButton.LeftButton or pressed is None or pressed[0] != released:
            return super().mouseReleaseEvent(event)
        cell = pressed[0]
        if cell.is_header:
            self.toggle_section(self.sections[cell.section][0])
        elif (record := self.record_for(cell)) is not None:
            self.open_requested.emit(record)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            steps = event.angleDelta().y() / 120
            if steps:
                self.set_tile_size(round(self.tile_size * (1.12 ** steps)), event.position())
            event.accept()
            return
        super().wheelEvent(event)

    def event(self, event) -> bool:
        # Trackpad pinch on macOS arrives as a native zoom gesture.
        if event.type() == QEvent.Type.NativeGesture and event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
            self.set_tile_size(round(self.tile_size * (1 + event.value())), event.position())
            return True
        return super().event(event)

    def context_menu(self, record: MediaRecord) -> QMenu:
        """What right-clicking a tile offers: opening it, and moving it to the Trash when that's possible."""
        menu = QMenu(self)
        menu.addAction("Open", lambda: self.open_requested.emit(record))
        if not self.offline:
            menu.addSeparator()
            trash = menu.addAction(TRASH_LABEL, lambda: self.delete_requested.emit(record))
            trash.setEnabled(not self.read_only)
            if self.read_only:
                trash.setToolTip(read_only_trash_reason())
        return menu

    def contextMenuEvent(self, event) -> None:
        cell = self._cell_at_position(QPointF(event.pos()))
        record = self.record_for(cell) if cell else None
        if record is not None:
            self.context_menu(record).exec(event.globalPos())

    def viewportEvent(self, event) -> bool:
        if event.type() == QEvent.Type.ToolTip:
            cell = self._cell_at_position(QPointF(event.pos()))
            record = self.record_for(cell) if cell else None
            if record is not None:
                kind = "Video" if record.is_video else "Live Photo" if record.is_live else "Photo"
                QToolTip.showText(event.globalPos(),
                                  f"{record.path.name}\n{kind}  ·  "
                                  f"{format_capture(record.captured_at, self.time_format)}", self.viewport())
            else:
                QToolTip.hideText()
            return True
        return super().viewportEvent(event)
