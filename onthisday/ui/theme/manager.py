from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from .colors import DARK, LIGHT, Palette
from .stylesheet import build_stylesheet


class ThemeManager(QObject):
    changed = Signal(str)

    def __init__(self, app: QApplication, preference: str = "system"):
        super().__init__(app)
        self.app = app
        self.preference = preference
        self._applied: str | None = None  # "light" or "dark": what the current stylesheet was built for
        # Applying a stylesheet restyles every widget, which takes a noticeable fraction of a second.
        # So it is redone only when light or dark really changes, and the system's changes arrive as
        # signals, not through an event filter that would run Python code for every event in the app.
        app.styleHints().colorSchemeChanged.connect(self._system_changed)
        app.paletteChanged.connect(self._system_changed)
        self.apply(preference)

    def _system_is_dark(self) -> bool:
        scheme = self.app.styleHints().colorScheme()
        if scheme != Qt.ColorScheme.Unknown:
            return scheme == Qt.ColorScheme.Dark
        return self.app.palette().color(QPalette.ColorRole.Window).lightness() < 128

    @property
    def resolved(self) -> str:
        return ("dark" if self._system_is_dark() else "light") if self.preference == "system" else self.preference

    @property
    def colors(self) -> Palette:
        return DARK if self.resolved == "dark" else LIGHT

    def apply(self, preference: str) -> None:
        if preference not in {"system", "light", "dark"}:
            preference = "system"
        self.preference = preference
        self._restyle()

    def _system_changed(self, *_args) -> None:
        if self.preference == "system":
            self._restyle()

    def _restyle(self) -> None:
        resolved = self.resolved
        if resolved == self._applied:
            return  # e.g. Settings saved without changing the theme, or a palette change within the same theme
        self._applied = resolved
        self.app.setStyleSheet(build_stylesheet(self.colors))
        self.changed.emit(self.preference)
