"""tools/build_app.py, without running PyInstaller."""

import importlib.util
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onthisday.core.constants import APP_NAME, VERSION

BUILD_APP = Path(__file__).resolve().parent.parent / "tools" / "build_app.py"


def load_build_app():
    spec = importlib.util.spec_from_file_location("build_app", BUILD_APP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BuildAppTests(unittest.TestCase):
    def setUp(self):
        self.build_app = load_build_app()

    def test_bundles_ffmpeg_and_names_the_app(self):
        arguments = self.build_app.pyinstaller_arguments(None)
        self.assertIn("imageio_ffmpeg", arguments[arguments.index("--collect-all") + 1])
        self.assertEqual(arguments[arguments.index("--name") + 1], APP_NAME)
        self.assertIn("--windowed", arguments)

    def test_mac_bundle_carries_the_version_and_is_re_signed(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp) / f"{APP_NAME}.app"
            (bundle / "Contents").mkdir(parents=True)
            with open(bundle / "Contents" / "Info.plist", "wb") as handle:
                plistlib.dump({"CFBundleIdentifier": self.build_app.BUNDLE_ID, "CFBundleShortVersionString": "0.0.0"}, handle)
            with patch.object(self.build_app.subprocess, "run") as run:
                self.build_app.finish_mac_bundle(bundle)
            with open(bundle / "Contents" / "Info.plist", "rb") as handle:
                info = plistlib.load(handle)
        self.assertEqual((info["CFBundleShortVersionString"], info["CFBundleVersion"]), (VERSION, VERSION))
        self.assertEqual(run.call_args.args[0][:2], ["codesign", "--force"])

    def test_windows_archive_is_named_after_version_and_platform(self):
        with tempfile.TemporaryDirectory() as temp:
            built = Path(temp) / "standalone" / APP_NAME
            built.mkdir(parents=True)
            (built / f"{APP_NAME}.exe").write_bytes(b"MZ")
            with patch.object(self.build_app, "DIST", Path(temp)), patch.object(self.build_app.sys, "platform", "win32"):
                archive = self.build_app.archive(built)
            self.assertEqual(archive.name, f"On-This-Day-{VERSION}-Windows.zip")
            self.assertTrue(archive.exists())


if __name__ == "__main__":
    unittest.main()
