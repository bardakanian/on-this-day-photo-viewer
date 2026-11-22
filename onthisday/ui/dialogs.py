from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QVBoxLayout)

from ..core.metadata import format_file_size
from ..core.preview_cache import CacheUsage
from ..core.settings import DEFAULT_PREVIEW_QUALITY, PREVIEW_HIGH, PREVIEW_STANDARD
from ..core.timeformat import TIME_12_HOUR, TIME_24_HOUR


def note(text: str) -> QLabel:
    """An explanation under a setting. Wrapped text needs the height its width implies, or the
    dialog opens too short and the last line is cut off."""
    label = QLabel(text)
    label.setProperty("muted", True)
    label.setWordWrap(True)
    policy = label.sizePolicy()
    policy.setHeightForWidth(True)
    policy.setVerticalPolicy(QSizePolicy.Policy.MinimumExpanding)
    label.setSizePolicy(policy)
    return label


class PreferencesDialog(QDialog):
    delete_previews_requested = Signal()
    open_videos_requested = Signal()

    def __init__(self, current_theme: str, save_previews: bool = True, current_time_format: str = TIME_12_HOUR,
                 parent=None, auto_rescan: bool = True, preview_quality: str = DEFAULT_PREVIEW_QUALITY):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setMinimumWidth(390)
        layout = QVBoxLayout(self)
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
        layout.addWidget(buttons)

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
