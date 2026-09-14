from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout


class PreferencesDialog(QDialog):
    def __init__(self, current_theme: str, parent=None):
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
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def selected_theme(self) -> str:
        return self.theme.currentData()
