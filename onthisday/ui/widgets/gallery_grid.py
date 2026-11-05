from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, QSize, Qt, Signal, Slot
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractScrollArea, QMenu, QToolTip

from ...core.gallery_layout import CARD_WIDTH, Cell, GalleryLayout, layout_sections
from ...core.media import get_cached_thumbnail, legacy_thumbnail_cache_path, thumbnail_cache_path
from ...core.models import MediaRecord
from ...core.workqueue import WorkQueue
from ..theme.colors import LIGHT, Palette
from ..theme.metrics import Metrics
from ..theme.typography import Typography

# Card geometry, relative to the card's top-left corner.
PREVIEW = QRect(8, 8, 248, 186)
DATE_LINE = QRect(8, 201, 248, 16)
NAME_LINE = QRect(8, 220, 248, 18)
DETAILS_LINE = QRect(8, 244, 248, 28)
PIXMAP_CACHE_SIZE = 240  # about 175 MB of Retina thumbnails; a screenful is 20 to 30
TRASH_LABEL = "Move to Trash"
FAILED = object()  # the thumbnail could not be made


def _thumbnail_key(record: MediaRecord) -> tuple:
    return str(record.path), record.file_size, record.modified_ns


def _load_scaled(path: Path | None, size: QSize) -> QImage | None:
    """Decode and scale a cached thumbnail. QImage is safe to use off the UI thread; QPixmap is not."""
    if path is None:
        return None
    image = QImage(str(path))
    if image.isNull():
        return None
    return image.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


class _Signals(QObject):
    loaded = Signal(object, object, bool)  # key, QImage or None, final


class ThumbnailLoader(QObject):
    """Loads gallery thumbnails in the background, emitting `loaded(key, image, final)` on the UI thread.

    A cached thumbnail is read on one queue; making a missing one (slow for videos) runs on
    another, so reading never waits behind ffmpeg. Both drop work scrolled out of view.
    """

    loaded = Signal(object, object, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._read = WorkQueue(4, "thumbnail-read")
        self._generate = WorkQueue(3, "thumbnail-generate")
        self._signals = _Signals()
        self._signals.loaded.connect(self.loaded)

    def request(self, record: MediaRecord, size: QSize) -> None:
        key = _thumbnail_key(record)
        emit = self._emit

        def generate():
            result = get_cached_thumbnail(record.path, record.media_type, record.file_size, record.modified_ns)
            emit(key, _load_scaled(result, size), True)

        def read():
            cached = thumbnail_cache_path(record.path, record.file_size, record.modified_ns)
            if cached.exists():
                emit(key, _load_scaled(cached, size), True)
                return
            # Show an older low-resolution thumbnail while the sharp one is made.
            legacy = legacy_thumbnail_cache_path(record.path, record.file_size, record.modified_ns)
            if legacy.exists():
                emit(key, _load_scaled(legacy, size), False)
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

    def _emit(self, key: tuple, image: QImage | None, final: bool) -> None:
        try:
            self._signals.loaded.emit(key, image, final)
        except RuntimeError:
            pass  # the window closed while loading


class GalleryGrid(QAbstractScrollArea):
    """The gallery's year sections and media cards, drawn rather than built from widgets.

    Only the cards on screen are painted and have thumbnails loaded, so very large days stay fast.
    """

    open_requested = Signal(object)    # MediaRecord
    delete_requested = Signal(object)  # MediaRecord

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QAbstractScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Photos and videos")
        self.viewport().setMouseTracking(True)
        self.verticalScrollBar().setSingleStep(48)
        self.colors: Palette = LIGHT
        self.root_folder: Path | None = None
        self.sections: list[tuple[int, list[MediaRecord]]] = []
        self.collapsed: set[int] = set()
        self.layout_: GalleryLayout = layout_sections([], [], 0)
        self.loader = ThumbnailLoader(self)
        self.loader.loaded.connect(self._thumbnail_loaded)
        self._pixmaps: OrderedDict[tuple, QPixmap | object] = OrderedDict()
        self._requested: set[tuple] = set()
        self._placeholders: set[tuple] = set()  # showing an old low-resolution thumbnail for now
        self._hover: tuple[Cell, str] | None = None
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
                     collapsed: set[int] | None = None) -> None:
        self.sections = sections
        self.root_folder = root_folder
        self.collapsed = {year for year in (collapsed or set()) if any(year == y for y, _ in sections)}
        self._hover = self._pressed = None
        self._relayout()

    def set_colors(self, colors: Palette) -> None:
        self.colors = colors
        self.viewport().update()

    def toggle_section(self, year: int) -> None:
        self.collapsed ^= {year}
        self._relayout()

    def record_for(self, cell: Cell) -> MediaRecord | None:
        if cell.is_header or not 0 <= cell.section < len(self.sections):
            return None
        records = self.sections[cell.section][1]
        return records[cell.item] if cell.item < len(records) else None

    def shutdown(self) -> None:
        self.loader.shutdown()

    # Layout and scrolling ------------------------------------------------------

    def _relayout(self) -> None:
        width = max(CARD_WIDTH, self.viewport().width() - 8)  # room for the scroll bar
        self.layout_ = layout_sections(
            [len(records) for _, records in self.sections],
            [year in self.collapsed for year, _ in self.sections],
            width,
        )
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
                    self._paint_card(painter, cell, record)
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
        title_rect = QRect(cell.x + 4, cell.y, metrics.horizontalAdvance(title) + 8, cell.height)
        if self._is_hover(cell, "header"):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c.surface_alt))
            painter.drawRoundedRect(QRectF(title_rect).adjusted(-6, 4, 6, -4), Metrics.RADIUS_SMALL, Metrics.RADIUS_SMALL)
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

    def _paint_card(self, painter: QPainter, cell: Cell, record: MediaRecord) -> None:
        c = self.colors
        card = QRectF(cell.x + 0.5, cell.y + 0.5, cell.width - 1, cell.height - 1)
        painter.setPen(QPen(QColor(c.accent if self._is_hover(cell, "preview") else c.border), 1))
        painter.setBrush(QColor(c.surface))
        painter.drawRoundedRect(card, Metrics.RADIUS_LARGE, Metrics.RADIUS_LARGE)

        preview = PREVIEW.translated(cell.x, cell.y)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(127, 127, 127, 26))
        painter.drawRoundedRect(QRectF(preview), 7, 7)
        pixmap = self._pixmaps.get(_thumbnail_key(record))
        if isinstance(pixmap, QPixmap):
            size = pixmap.deviceIndependentSize()
            target = QRectF(0, 0, size.width(), size.height())
            target.moveCenter(QRectF(preview).center())
            painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        elif pixmap is FAILED:
            painter.setFont(self._body_font)
            painter.setPen(QColor(c.text_muted))
            painter.drawText(preview, Qt.AlignmentFlag.AlignCenter,
                             "Video preview unavailable" if record.is_video else "Preview unavailable")

        painter.setFont(self._caption_font)
        painter.setPen(QColor(c.text_subtle))
        kind = "VIDEO" if record.is_video else "PHOTO"
        painter.drawText(DATE_LINE.translated(cell.x, cell.y), Qt.AlignmentFlag.AlignVCenter,
                         f"{kind}  ·  {record.captured_at:%B %d, %Y  •  %H:%M}")

        painter.setFont(self._body_font)
        painter.setPen(QColor(c.text))
        name_rect = NAME_LINE.translated(cell.x, cell.y)
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(self._body_font).elidedText(record.path.name, Qt.TextElideMode.ElideMiddle, name_rect.width()))

        trash = self._trash_rect(cell)
        folder_rect = QRect(DETAILS_LINE.translated(cell.x, cell.y))
        folder_rect.setRight(int(trash.left()) - 8)
        painter.setPen(QColor(c.text_muted))
        painter.drawText(folder_rect, Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(self._body_font).elidedText(self._folder_text(record), Qt.TextElideMode.ElideMiddle, folder_rect.width()))

        danger = QColor(c.danger)
        hover_fill = QColor(danger)
        hover_fill.setAlpha(28)
        painter.setPen(QPen(danger, 1))
        painter.setBrush(hover_fill if self._is_hover(cell, "trash") else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(trash.adjusted(0.5, 0.5, -0.5, -0.5), Metrics.RADIUS_SMALL, Metrics.RADIUS_SMALL)
        painter.drawText(trash, Qt.AlignmentFlag.AlignCenter, TRASH_LABEL)

    def _trash_rect(self, cell: Cell) -> QRectF:
        width = QFontMetrics(self._body_font).horizontalAdvance(TRASH_LABEL) + 22
        line = DETAILS_LINE.translated(cell.x, cell.y)
        return QRectF(line.right() + 1 - width, line.top(), width, line.height())

    def _folder_text(self, record: MediaRecord) -> str:
        try:
            relative = record.path.parent.relative_to(self.root_folder.resolve()) if self.root_folder else None
        except (ValueError, OSError):
            relative = None
        if relative is None:
            return str(record.path.parent)
        return "Library" if str(relative) == "." else str(relative)

    # Thumbnails ----------------------------------------------------------------

    def _request_thumbnails(self, cells: list[Cell]) -> None:
        ratio = self.devicePixelRatioF()
        size = QSize(round(PREVIEW.width() * ratio), round(PREVIEW.height() * ratio))
        wanted = []
        for cell in cells:
            record = self.record_for(cell)
            if record is None:
                continue
            key = _thumbnail_key(record)
            wanted.append(key)
            if key in self._pixmaps:
                self._pixmaps.move_to_end(key)  # keep what's on screen in the cache
            if key not in self._requested and (key not in self._pixmaps or key in self._placeholders):
                self._requested.add(key)
                self.loader.request(record, size)
        for key in self.loader.focus(wanted):
            self._requested.discard(key)  # scrolled away; asked for again when it comes back

    @Slot(object, object, bool)
    def _thumbnail_loaded(self, key: tuple, image: QImage | None, final: bool) -> None:
        if image is None:
            if final:
                self._requested.discard(key)
                self._pixmaps[key] = FAILED
            return
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(self.devicePixelRatioF())
        self._pixmaps[key] = pixmap
        self._pixmaps.move_to_end(key)
        if final:
            self._requested.discard(key)
            self._placeholders.discard(key)
        else:
            self._placeholders.add(key)
        while len(self._pixmaps) > PIXMAP_CACHE_SIZE:
            self._pixmaps.popitem(last=False)
        self.viewport().update()

    def clear_thumbnails(self) -> None:
        """Forget loaded thumbnails (for example after the files on disk changed)."""
        self.loader.clear()
        self._pixmaps.clear()
        self._requested.clear()
        self._placeholders.clear()

    # Interaction ---------------------------------------------------------------

    def _target(self, position: QPointF) -> tuple[Cell, str] | None:
        x, y = position.x(), position.y() + self._offset()
        cell = self.layout_.cell_at(x, y)
        if cell is None:
            return None
        if cell.is_header:
            return cell, "header"
        local = QPointF(x - cell.x, y - cell.y)
        if self._trash_rect(Cell(0, 0, 0, 0, cell.width, cell.height)).contains(local):
            return cell, "trash"
        if QRectF(PREVIEW).contains(local):
            return cell, "preview"
        if QRectF(NAME_LINE).contains(local):
            return cell, "name"
        if QRectF(DETAILS_LINE).contains(local):
            return cell, "folder"
        return cell, "card"

    def _is_hover(self, cell: Cell, part: str) -> bool:
        return self._hover is not None and self._hover[0] == cell and self._hover[1] == part

    def mouseMoveEvent(self, event) -> None:
        target = self._target(event.position())
        if target != self._hover:
            self._hover = target
            clickable = target is not None and target[1] in {"header", "trash", "preview"}
            self.viewport().setCursor(QCursor(Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor))
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover is not None:
            self._hover = None
            self.viewport().update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = self._target(event.position())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        pressed, self._pressed = self._pressed, None
        if event.button() != Qt.MouseButton.LeftButton or pressed is None or pressed != self._target(event.position()):
            return super().mouseReleaseEvent(event)
        cell, part = pressed
        if part == "header":
            self.toggle_section(self.sections[cell.section][0])
        elif part == "trash" and (record := self.record_for(cell)) is not None:
            self.delete_requested.emit(record)
        elif part == "preview" and (record := self.record_for(cell)) is not None:
            self.open_requested.emit(record)

    def contextMenuEvent(self, event) -> None:
        target = self._target(QPointF(event.pos()))
        record = self.record_for(target[0]) if target else None
        if record is None:
            return
        menu = QMenu(self)
        menu.addAction("Open", lambda: self.open_requested.emit(record))
        menu.addSeparator()
        menu.addAction(TRASH_LABEL, lambda: self.delete_requested.emit(record))
        menu.exec(event.globalPos())

    def viewportEvent(self, event) -> bool:
        if event.type() == QEvent.Type.ToolTip:
            target = self._target(QPointF(event.pos()))
            record = self.record_for(target[0]) if target else None
            tips = {
                "name": str(record.path) if record else "",
                "folder": str(record.path.parent) if record else "",
                "trash": f"Move {record.path.name} to Trash" if record else "",
            }
            text = tips.get(target[1], "") if target else ""
            if text:
                QToolTip.showText(event.globalPos(), text, self.viewport())
            else:
                QToolTip.hideText()
            return True
        return super().viewportEvent(event)
