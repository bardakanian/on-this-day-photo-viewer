from collections import defaultdict
from datetime import date
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QStackedWidget, QVBoxLayout, QWidget

from ...core.models import MediaRecord
from ..theme.colors import Palette
from ..widgets.common import EmptyState, PageHeader
from ..widgets.gallery_grid import GalleryGrid


class GalleryPage(QWidget):
    choose_folder_requested = Signal()
    open_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 20, 0)
        outer.setSpacing(20)
        self.header = PageHeader("On This Day", "Rediscover photos and videos from years past")
        outer.addWidget(self.header)
        self.summary = QLabel()
        self.summary.setProperty("muted", True)
        outer.addWidget(self.summary)
        self.results = QStackedWidget()
        self.grid = GalleryGrid()
        self.grid.open_requested.connect(self.open_requested)
        self.grid.delete_requested.connect(self.delete_requested)
        self.results.addWidget(self.grid)
        self.empty = EmptyState("", "")
        self.empty.action_requested.connect(self.choose_folder_requested)
        empty_page = QWidget()
        empty_layout = QVBoxLayout(empty_page)
        empty_layout.setContentsMargins(0, 0, 8, 24)
        empty_layout.addWidget(self.empty)
        empty_layout.addStretch()
        self.results.addWidget(empty_page)
        outer.addWidget(self.results, 1)
        # Every record for the shown day, in display order; the viewer steps through this list.
        self.records: list[MediaRecord] = []
        self._shown_key: tuple | None = None

    def set_theme_colors(self, colors: Palette) -> None:
        self.grid.set_colors(colors)

    def set_time_format(self, time_format: str) -> None:
        self.grid.set_time_format(time_format)

    def cancel_pending(self) -> None:
        """Drop queued thumbnail work; running jobs just finish."""
        self.grid.loader.clear()

    def shutdown(self) -> None:
        self.grid.shutdown()

    def show_unavailable(self, folder: Path) -> None:
        self.cancel_pending()
        self.records = []
        self.grid.set_sections([], folder)
        self.summary.setText(str(folder))
        self.empty.set_content("Library folder unavailable",
                               f"Connect the drive or network share that holds “{folder.name or folder}”. "
                               "Your photos appear again as soon as it's back.")
        self.results.setCurrentIndex(1)

    def show_records(self, records: list[MediaRecord], selected_date: date, media_filter: str, folder: Path | None) -> None:
        self.cancel_pending()
        # Reloading the same day (after a rescan or a deletion) keeps the scroll position and collapsed years.
        key = (folder, selected_date, media_filter)
        same_view = key == self._shown_key
        self._shown_key = key
        scroll = self.grid.verticalScrollBar().value() if same_view else 0
        collapsed = self.grid.collapsed if same_view else set()
        display_date = f"{selected_date:%B} {selected_date.day}"
        self.header.title.setText(display_date)
        self.header.subtitle.setText(f"{media_filter} captured on this date across your library")
        self.records = []
        if folder is None or not records:
            self.grid.set_sections([], folder)
            if folder is None:
                self.summary.clear()
                self.empty.set_content("Choose your media library",
                                       "Select a folder to begin rediscovering moments from years past.", "Choose Folder")
            else:
                self.summary.setText(str(folder))
                self.empty.set_content(f"No {media_filter.lower()} for {display_date}",
                                       "Try another day, change the media filter, or rescan your library.")
            self.results.setCurrentIndex(1)
            return
        photos = sum(record.media_type == "image" for record in records)
        self.summary.setText(f"{len(records):,} items  ·  {photos:,} photos  ·  {len(records) - photos:,} videos")
        grouped: dict[int, list[MediaRecord]] = defaultdict(list)
        for record in records:
            grouped[record.captured_at.year].append(record)
        sections = [(year, grouped[year]) for year in sorted(grouped, reverse=True)]
        for _, items in sections:
            self.records.extend(items)
        self.grid.set_sections(sections, folder, collapsed)
        self.results.setCurrentIndex(0)
        self.grid.verticalScrollBar().setValue(scroll)
