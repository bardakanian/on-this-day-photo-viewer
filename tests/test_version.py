"""The version number: shown in the title and launcher, and recorded in CHANGELOG.md."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import plistlib
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from onthisday.core.constants import APP_NAME, VERSION
from onthisday.core.settings import AppSettings, SettingsStore
from onthisday.ui.main_window import MainWindow

PROJECT = Path(__file__).resolve().parent.parent
APP = QApplication.instance() or QApplication([])


class VersionTests(unittest.TestCase):
    def test_version_is_semantic(self):
        self.assertRegex(VERSION, r"^\d+\.\d+\.\d+$")

    def test_window_title_shows_version(self):
        # Default settings, so the test doesn't depend on (or touch) the user's library.
        with patch.object(SettingsStore, "load", return_value=AppSettings()):
            window = MainWindow(APP)
        try:
            self.assertEqual(window.windowTitle(), f"{APP_NAME} {VERSION}")
        finally:
            window.close()

    def test_changelog_has_entry_for_current_version(self):
        changelog = (PROJECT / "CHANGELOG.md").read_text(encoding="utf-8")
        versions = re.findall(r"^## (\d+\.\d+\.\d+) — \d{4}-\d{2}-\d{2}$", changelog, re.MULTILINE)
        self.assertIn(VERSION, versions, "add a CHANGELOG.md entry for the new VERSION")
        self.assertEqual(versions[0], VERSION, "the newest CHANGELOG.md entry should be the current VERSION")

    def test_launcher_bundle_carries_version(self):
        spec = importlib.util.spec_from_file_location("make_launcher", PROJECT / "tools" / "make_launcher.py")
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / ".venv" / "bin").mkdir(parents=True)
            (project / ".venv" / "bin" / "python").touch()
            with patch.object(launcher, "PROJECT", project), patch.object(launcher, "build_icns", return_value=False):
                bundle = launcher.build(project / "dist")
            with open(bundle / "Contents" / "Info.plist", "rb") as handle:
                info = plistlib.load(handle)
        self.assertEqual(info["CFBundleShortVersionString"], VERSION)
        self.assertEqual(info["CFBundleVersion"], VERSION)


if __name__ == "__main__":
    unittest.main()
