"""Build a standalone On This Day that runs without Python or this project folder.

    python tools/build_app.py              # macOS: dist/standalone/On This Day.app; Windows: dist/standalone/On This Day/
    python tools/build_app.py --install    # macOS: also copy the app into /Applications (replaces the launcher)

It also writes a zip to share, dist/On-This-Day-<version>-<macOS|Windows>.zip. Needs PyInstaller
(pip install -r requirements-dev.txt). Unlike tools/make_launcher.py, the result bundles its own
Python, Qt and ffmpeg, so later code changes need a new build.

The macOS app is signed ad hoc, not with an Apple Developer ID, so on another Mac the first launch
needs right-click > Open (or System Settings > Privacy & Security > Open Anyway).
"""

import argparse
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_launcher import BUNDLE_ID as LAUNCHER_BUNDLE_ID, ICO_SIZES, build_icns, draw_icon  # noqa: E402
from onthisday.core.constants import APP_NAME, VERSION  # noqa: E402

BUNDLE_ID = "local.onthisday.app"
DIST = PROJECT / "dist"
OUTPUT = DIST / "standalone"
WORK = PROJECT / "build" / "pyinstaller"


def platform_name() -> str:
    return {"darwin": "macOS", "win32": "Windows"}.get(sys.platform, sys.platform)


def make_icon() -> Path | None:
    WORK.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        icon = WORK / "AppIcon.icns"
        return icon if build_icns(icon) else None
    icon = WORK / "AppIcon.ico"
    draw_icon(256).save(icon, sizes=ICO_SIZES)
    return icon


def pyinstaller_arguments(icon: Path | None) -> list[str]:
    arguments = [
        str(PROJECT / "app.py"),
        "--name", APP_NAME,
        "--windowed",  # no console window; a .app bundle on macOS
        "--noconfirm", "--clean",
        "--distpath", str(OUTPUT),
        "--workpath", str(WORK),
        "--specpath", str(WORK),
        # imageio-ffmpeg's ffmpeg binary is package data, which PyInstaller doesn't find on its own.
        "--collect-all", "imageio_ffmpeg",
        "--osx-bundle-identifier", BUNDLE_ID,
    ]
    if icon is not None:
        arguments += ["--icon", str(icon)]
    return arguments


def finish_mac_bundle(bundle: Path) -> None:
    """Stamp the version into Info.plist, then re-sign, since editing the bundle breaks its signature."""
    info_path = bundle / "Contents" / "Info.plist"
    with open(info_path, "rb") as handle:
        info = plistlib.load(handle)
    info.update({
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.photography",
    })
    with open(info_path, "wb") as handle:
        plistlib.dump(info, handle)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(bundle)], check=True, capture_output=True)


def archive(built: Path) -> Path:
    target = DIST / f"{APP_NAME.replace(' ', '-')}-{VERSION}-{platform_name()}.zip"
    target.unlink(missing_ok=True)
    if sys.platform == "darwin":
        # ditto keeps the bundle's symlinks, permissions and signature intact; zipfile does not.
        subprocess.run(["ditto", "-c", "-k", "--keepParent", str(built), str(target)], check=True)
    else:
        shutil.make_archive(str(target.with_suffix("")), "zip", built.parent, built.name)
    return target


def install(bundle: Path) -> Path:
    target = Path("/Applications") / bundle.name
    if target.exists():
        try:
            with open(target / "Contents" / "Info.plist", "rb") as handle:
                existing = plistlib.load(handle).get("CFBundleIdentifier")
        except (OSError, plistlib.InvalidFileException):
            existing = None
        if existing not in {BUNDLE_ID, LAUNCHER_BUNDLE_ID}:
            sys.exit(f"{target} exists and isn't On This Day; not replacing it.")
        shutil.rmtree(target)
    shutil.copytree(bundle, target, symlinks=True)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--install", action="store_true", help="macOS: copy the app into /Applications")
    args = parser.parse_args()
    if sys.platform not in {"darwin", "win32"}:
        sys.exit("Standalone builds are made for macOS and Windows.")
    try:
        import PyInstaller.__main__
    except ImportError:
        sys.exit("PyInstaller is not installed. Run: pip install -r requirements-dev.txt")

    PyInstaller.__main__.run(pyinstaller_arguments(make_icon()))
    if sys.platform == "darwin":
        built = OUTPUT / f"{APP_NAME}.app"
        finish_mac_bundle(built)
    else:
        built = OUTPUT / APP_NAME
    print(f"Built {built}")
    print(f"Archived {archive(built)}")
    if args.install and sys.platform == "darwin":
        print(f"Installed {install(built)}")


if __name__ == "__main__":
    main()
