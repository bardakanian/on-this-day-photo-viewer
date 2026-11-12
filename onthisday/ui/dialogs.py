from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout

from ..core.timeformat import TIME_12_HOUR, TIME_24_HOUR


class PreferencesDialog(QDialog):
    def __init__(self, current_theme: str, save_previews: bool = True, current_time_format: str = TIME_12_HOUR,
                 parent=None):
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
        note = QLabel("System automatically follows your macOS appearance setting.")
        note.setProperty("muted", True)
        note.setWordWrap(True)
        layout.addWidget(note)
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
        self.save_previews = QCheckBox("Save a preview of every photo and video")
        self.save_previews.setChecked(save_previews)
        layout.addWidget(self.save_previews)
        previews_note = QLabel(
            "Lets you browse the library while its drive is disconnected, and makes scrolling "
            "faster. Previews are made in the background after each scan and take about 35 KB "
            "per item (roughly 3.5 GB for 100,000 items)."
        )
        previews_note.setProperty("muted", True)
        previews_note.setWordWrap(True)
        layout.addWidget(previews_note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def selected_theme(self) -> str:
        return self.theme.currentData()

    @property
    def selected_save_previews(self) -> bool:
        return self.save_previews.isChecked()

    @property
    def selected_time_format(self) -> str:
        return self.time_format.currentData()
