"""Windows-specific behaviour, checked on any platform with the Windows parts mocked."""

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from onthisday.core import media

LAUNCHER = Path(__file__).resolve().parent.parent / "tools" / "make_launcher.py"
CREATE_NO_WINDOW = 0x08000000


def load_launcher():
    spec = importlib.util.spec_from_file_location("make_launcher", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConsoleWindowTests(unittest.TestCase):
    def test_no_console_flag_only_on_windows(self):
        self.assertEqual(media._NO_CONSOLE, CREATE_NO_WINDOW if os.name == "nt" else 0)

    @unittest.skipUnless(media.FFMPEG_ENABLED, "ffmpeg not installed")
    def test_every_ffmpeg_call_hides_its_console(self):
        finished = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(media, "_NO_CONSOLE", CREATE_NO_WINDOW), \
                patch.object(media.subprocess, "run", return_value=finished) as run:
            source = Path(temp) / "clip.mp4"
            source.write_bytes(b"video")
            media.get_video_metadata_date(source)
            media._video_thumbnail(source, Path(temp) / "thumb.jpg")
        self.assertGreaterEqual(run.call_count, 3)  # metadata, then a thumbnail at 1 s and at 0 s
        for call in run.call_args_list:
            self.assertEqual(call.kwargs.get("creationflags"), CREATE_NO_WINDOW, call)


class WindowsShortcutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "OnThisDay"
        (self.project / ".venv" / "Scripts").mkdir(parents=True)
        (self.project / ".venv" / "Scripts" / "pythonw.exe").write_bytes(b"")
        (self.project / "app.py").write_text("")
        self.appdata = self.root / "AppData" / "Roaming"
        self.profile = self.root / "User Name"
        self.launcher = load_launcher()

    def tearDown(self):
        self.temp.cleanup()

    def install(self, desktop: bool):
        environment = {"APPDATA": str(self.appdata), "USERPROFILE": str(self.profile)}
        with patch.object(self.launcher, "PROJECT", self.project), \
                patch.dict(os.environ, environment), \
                patch.object(self.launcher.subprocess, "run") as run:
            links = self.launcher.install_windows(desktop)
        return links, run

    def test_start_menu_shortcut_runs_app_without_console(self):
        links, run = self.install(desktop=False)
        start_menu = self.appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        self.assertEqual(links, [start_menu / "On This Day.lnk"])
        command = run.call_args.args[0]
        self.assertEqual(command[0], "powershell")
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["OTD_LINK"], str(start_menu / "On This Day.lnk"))
        self.assertEqual(env["OTD_TARGET"], str(self.project / ".venv" / "Scripts" / "pythonw.exe"))
        # Quoted, so a project folder with spaces still works.
        self.assertEqual(env["OTD_ARGUMENTS"], f'"{self.project / "app.py"}"')
        self.assertEqual(env["OTD_WORKDIR"], str(self.project))

    def test_icon_has_standard_sizes(self):
        self.install(desktop=False)
        with Image.open(self.project / "dist" / "On This Day.ico") as icon:
            self.assertIn((256, 256), icon.info["sizes"])
            self.assertIn((16, 16), icon.info["sizes"])

    def test_desktop_shortcut_is_optional(self):
        links, run = self.install(desktop=True)
        self.assertEqual(links[-1], self.profile / "Desktop" / "On This Day.lnk")
        self.assertEqual(run.call_count, 2)

    def test_missing_virtual_environment_is_reported(self):
        (self.project / ".venv" / "Scripts" / "pythonw.exe").unlink()
        with self.assertRaises(SystemExit):
            self.install(desktop=False)


if __name__ == "__main__":
    unittest.main()
