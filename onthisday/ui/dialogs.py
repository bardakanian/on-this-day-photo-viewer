from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)

from ..core.metadata import format_file_size
from ..core.preview_cache import CacheUsage
from ..core.settings import DEFAULT_PREVIEW_QUALITY, PREVIEW_HIGH, PREVIEW_STANDARD
from ..core.timeformat import TIME_12_HOUR, TIME_24_HOUR


class Note(QLabel):
    """An explanation under a setting.

    Wrapped text needs the height its own width implies. Asking for that through the size policy
    isn't enough on every platform: how many lines the text takes depends on the system font, so
    the height is claimed again whenever the label is resized, and the dialog grows to fit.
    """

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setProperty("muted", True)
        self.setWordWrap(True)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        policy.setVerticalPolicy(QSizePolicy.Policy.MinimumExpanding)
        self.setSizePolicy(policy)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        needed = self.heightForWidth(self.width())
        if needed != self.minimumHeight():  # grows and shrinks, so an earlier width leaves no gap
            self.setMinimumHeight(needed)


def note(text: str) -> Note:
    return Note(text)


class PreferencesDialog(QDialog):
    delete_previews_requested = Signal()
    open_videos_requested = Signal()

    def __init__(self, current_theme: str, save_previews: bool = True, current_time_format: str = TIME_12_HOUR,
                 parent=None, auto_rescan: bool = True, preview_quality: str = DEFAULT_PREVIEW_QUALITY):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setMinimumWidth(390)
        # The settings scroll, so a large system font or a small screen can't hide the buttons.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._scroll = scroll = QScrollArea()
        self._sized = False
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(18)
        heading = QLabel("Appearance")
        heading.setProperty("role", "section")
        layout.addWidget(heading)
        form = QFormLayout()
        form.setSpacing(12)
        self.theme = QComboBox()
        self.theme.addItem("Follow system appearance", "system")
        self.theme.addItem("Light", "light")
        self.theme.addItem("Dark", "dark")
        self.theme.setCurrentIndex(max(0, self.theme.findData(current_theme)))
        form.addRow("Theme", self.theme)
        layout.addLayout(form)
        layout.addWidget(note("System automatically follows your macOS appearance setting."))
        date_heading = QLabel("Date and Time")
        date_heading.setProperty("role", "section")
        layout.addWidget(date_heading)
        date_form = QFormLayout()
        date_form.setSpacing(12)
        self.time_format = QComboBox()
        self.time_format.addItem("12-hour (2:05 PM)", TIME_12_HOUR)
        self.time_format.addItem("24-hour (14:05)", TIME_24_HOUR)
        self.time_format.setCurrentIndex(max(0, self.time_format.findData(current_time_format)))
        date_form.addRow("Time format", self.time_format)
        layout.addLayout(date_form)
        library = QLabel("Library")
        library.setProperty("role", "section")
        layout.addWidget(library)
        videos_row = QHBoxLayout()
        videos_row.setSpacing(12)
        videos_row.addWidget(note("Browse every indexed video in a searchable, sortable table."), 1)
        self.open_videos = QPushButton("Video Library…")
        self.open_videos.setToolTip("Open the Video Library")
        self.open_videos.clicked.connect(self.open_videos_requested)
        self.open_videos.clicked.connect(self.reject)  # it opens behind this dialog
        videos_row.addWidget(self.open_videos)
        layout.addLayout(videos_row)
        self.auto_rescan = QCheckBox("Check the library for changes when I return to the app")
        self.auto_rescan.setChecked(auto_rescan)
        layout.addWidget(self.auto_rescan)
        layout.addWidget(note(
            "At most every 10 minutes, and each time while the library's drive is disconnected. "
            "When this is off, the library is only checked when you choose Rescan."))
        self.save_previews = QCheckBox("Save a preview of every photo and video")
        self.save_previews.setChecked(save_previews)
        layout.addWidget(self.save_previews)
        layout.addWidget(note(
            "Lets you browse the library while its drive is disconnected, and makes scrolling "
            "faster. Previews are made in the background after each scan."))
        quality_form = QFormLayout()
        quality_form.setSpacing(12)
        self.preview_quality = QComboBox()
        self.preview_quality.addItem("High — sharper, larger tiles stay clear", PREVIEW_HIGH)
        self.preview_quality.addItem("Standard — smaller previews, less disk space", PREVIEW_STANDARD)
        self.preview_quality.setCurrentIndex(max(0, self.preview_quality.findData(preview_quality)))
        self.preview_quality.setAccessibleName("Preview quality")
        self.preview_quality.setToolTip("High previews are 1024 px (about 140 KB each); Standard are 512 px (about 40 KB)")
        quality_form.addRow("Preview quality", self.preview_quality)
        layout.addLayout(quality_form)
        layout.addWidget(note(
            "Changing this remakes every preview in the background, which takes a while for a "
            "large library. High uses roughly three times the disk space of Standard."))
        cache_row = QHBoxLayout()
        cache_row.setSpacing(12)
        self.cache_label = QLabel("Saved previews: counting…")
        self.cache_label.setWordWrap(True)
        cache_row.addWidget(self.cache_label, 1)
        self.delete_previews = QPushButton("Delete All Previews…")
        self.delete_previews.setToolTip("Delete every saved preview to free disk space")
        self.delete_previews.setEnabled(False)  # until the cache has been counted
        self.delete_previews.clicked.connect(self.delete_previews_requested)
        cache_row.addWidget(self.delete_previews)
        layout.addLayout(cache_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        button_row = QWidget()
        button_layout = QVBoxLayout(button_row)
        button_layout.setContentsMargins(24, 12, 24, 16)
        button_layout.addWidget(buttons)
        outer.addWidget(button_row)
        # A scroll area's own hint ignores what's inside it, so the dialog is sized from the content:
        # a comfortable reading width, and tall enough for the settings unless the screen is smaller.
        width = max(self.minimumWidth(), min(content.sizeHint().width(), 480))
        needed = content.sizeHint().height() + button_row.sizeHint().height()
        self.resize(width, min(needed, self._room_on_screen()))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._sized:
            return
        self._sized = True
        # How much taller the laid-out settings are than the room they were given: wrapped text
        # takes the height its final width needs, which is only known once it has been laid out.
        short_by = self._scroll.widget().height() - self._scroll.viewport().height()
        if short_by > 0:
            self.resize(self.width(), min(self.height() + short_by, self._room_on_screen()))

    @staticmethod
    def _room_on_screen() -> int:
        screen = QApplication.primaryScreen()
        return round(screen.availableGeometry().height() * 0.9) if screen else 900

    def set_cache_usage(self, usage: CacheUsage | None, deleting: bool = False) -> None:
        """Show how much the saved previews take; None while they're being counted."""
        if deleting:
            self.cache_label.setText("Saved previews: deleting…")
        elif usage is None:
            self.cache_label.setText("Saved previews: counting…")
        elif usage.files == 0:
            self.cache_label.setText("Saved previews: none")
        else:
            noun = "file" if usage.files == 1 else "files"
            self.cache_label.setText(f"Saved previews: {format_file_size(usage.size)} ({usage.files:,} {noun})")
        self.delete_previews.setEnabled(not deleting and usage is not None and usage.files > 0)

    @property
    def selected_theme(self) -> str:
        return self.theme.currentData()

    @property
    def selected_save_previews(self) -> bool:
        return self.save_previews.isChecked()

    @property
    def selected_preview_quality(self) -> str:
        return self.preview_quality.currentData()

    @property
    def selected_auto_rescan(self) -> bool:
        return self.auto_rescan.isChecked()

    @property
    def selected_time_format(self) -> str:
        return self.time_format.currentData()
