"""Compatibility entry point for the PySide6 application."""

import logging
import sys

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from onthisday.core.constants import APP_DIR
from onthisday.ui.main_window import MainWindow


def configure_logging() -> None:
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=APP_DIR / "on_this_day.log",
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    except OSError:
        logging.basicConfig(level=logging.INFO)


def main() -> int:
    QCoreApplication.setOrganizationName("On This Day")
    QCoreApplication.setApplicationName("On This Day")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationDisplayName("On This Day")
    app.setStyle("Fusion")
    configure_logging()

    def report_exception(exc_type, exc_value, exc_traceback):
        logging.getLogger(__name__).exception(
            "Unhandled application error", exc_info=(exc_type, exc_value, exc_traceback)
        )
        QMessageBox.critical(
            None, "Unexpected error",
            "On This Day encountered an unexpected problem. Details were written to the application log.",
        )

    sys.excepthook = report_exception
    window = MainWindow(app)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
