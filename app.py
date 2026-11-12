"""Compatibility entry point for the PySide6 application."""

import logging
import sys

from PySide6.QtCore import QCoreApplication, QLoggingCategory, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from onthisday.core.constants import APP_DIR, APP_NAME, VERSION
from onthisday.ui.main_window import MainWindow


def configure_logging() -> None:
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=APP_DIR / "on_this_day.log",
            encoding="utf-8",  # the default on Windows is a legacy code page that garbles "·" and file names
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    except OSError:
        logging.basicConfig(level=logging.INFO)


def quiet_qt_logging() -> None:
    """Hide Qt Multimedia's informational chatter (the FFmpeg banner and per-file stream dump).
    Warnings and errors still come through; QT_LOGGING_RULES can turn the messages back on."""
    QLoggingCategory.setFilterRules(
        "qt.multimedia.ffmpeg.info=false\n"
        "qt.multimedia.ffmpeg.*.info=false\n"
        "qt.rhi.*.info=false"
    )


def preload_ffmpeg_dlls() -> None:
    """Load PySide6's FFmpeg DLLs by full path so Qt's FFmpeg media plugin can find them.

    Qt's plugin finds them through PATH, which Windows ignores for packaged apps such as the
    Microsoft Store Python. The plugin then fails to load and Qt silently falls back to Windows
    Media Foundation, which can't play many videos ("Media session serious error."). Once a DLL
    is loaded, Windows reuses it for any later lookup by the same name."""
    if sys.platform != "win32":
        return
    import ctypes
    from pathlib import Path

    import PySide6

    package_dir = Path(PySide6.__file__).resolve().parent
    # Dependencies before the DLLs that import them.
    for prefix in ("avutil", "swresample", "swscale", "avcodec", "avformat"):
        for dll in package_dir.glob(f"{prefix}-*.dll"):
            try:
                ctypes.WinDLL(str(dll))
            except OSError:
                logging.getLogger(__name__).warning("Could not preload %s", dll.name, exc_info=True)


def main() -> int:
    preload_ffmpeg_dlls()
    quiet_qt_logging()
    QCoreApplication.setOrganizationName(APP_NAME)
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(VERSION)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationDisplayName(APP_NAME)
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
    window.start_stall_watch()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
