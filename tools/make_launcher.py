"""Build a small macOS launcher app ("On This Day.app") that runs this project.

    python tools/make_launcher.py              # builds dist/On This Day.app and installs it in /Applications
    python tools/make_launcher.py --user       # installs in ~/Applications instead
    python tools/make_launcher.py --no-install # only builds dist/On This Day.app

The launcher contains no code of its own: it runs app.py with the project's .venv, so it
always starts the latest code. Re-run this script if you move the project folder.
Output and errors from the app go to ~/.on_this_day_photo_viewer/launcher.log.
"""

import argparse
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

PROJECT = Path(__file__).resolve().parent.parent
APP_NAME = "On This Day"
BUNDLE_ID = "local.onthisday.launcher"
EXECUTABLE = "launcher"
ICON_SIZES = (16, 32, 64, 128, 256, 512, 1024)


def draw_icon(size: int = 1024) -> Image.Image:
    """A rounded blue tile with a tilted calendar page holding a photo, in the app's accent colours."""
    scale = size / 1024
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Background tile: vertical gradient from the theme accent to a deeper indigo.
    tile = Image.new("RGBA", (size, size))
    top, bottom = (120, 149, 255), (41, 68, 181)
    pixels = tile.load()
    for y in range(size):
        t = y / (size - 1)
        colour = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,)
        for x in range(size):
            pixels[x, y] = colour
    mask = Image.new("L", (size, size), 0)
    margin = round(100 * scale)
    ImageDraw.Draw(mask).rounded_rectangle((margin, margin, size - margin, size - margin),
                                           radius=round(185 * scale), fill=255)
    icon.paste(tile, (0, 0), mask)

    # Calendar page: red header band with binding rings, and a small photo (sun and hills) as the day.
    card_w, card_h = round(560 * scale), round(600 * scale)
    card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    radius = round(40 * scale)
    draw.rounded_rectangle((0, 0, card_w - 1, card_h - 1), radius=radius, fill=(255, 255, 255, 255))
    header = round(150 * scale)
    draw.rounded_rectangle((0, 0, card_w - 1, header), radius=radius, fill=(232, 72, 85, 255))
    draw.rectangle((0, header - radius, card_w - 1, header), fill=(232, 72, 85, 255))
    ring_w, ring_h = round(30 * scale), round(70 * scale)
    for cx in (card_w * 0.3, card_w * 0.7):
        draw.rounded_rectangle((cx - ring_w / 2, header * 0.25 - ring_h / 2, cx + ring_w / 2, header * 0.25 + ring_h / 2),
                               radius=ring_w // 2, fill=(255, 255, 255, 235))
    pad = round(48 * scale)
    left, upper, right, lower = pad, header + pad, card_w - pad, card_h - pad
    draw.rounded_rectangle((left, upper, right, lower), radius=round(18 * scale), fill=(222, 233, 255, 255))
    width, height = right - left, lower - upper
    draw.ellipse((left + width * 0.62, upper + height * 0.14, left + width * 0.84, upper + height * 0.36),
                 fill=(255, 196, 61, 255))
    draw.polygon([(left, lower), (left + width * 0.36, upper + height * 0.46), (left + width * 0.62, lower)],
                 fill=(66, 99, 235, 255))
    draw.polygon([(left + width * 0.34, lower), (left + width * 0.68, upper + height * 0.58), (right, lower - height * 0.18),
                  (right, lower)], fill=(41, 68, 181, 255))

    rotated = card.rotate(6, resample=Image.Resampling.BICUBIC, expand=True)
    # Blur on a padded canvas so the shadow fades out instead of stopping at a hard edge.
    pad = round(60 * scale)
    shadow = Image.new("RGBA", (rotated.width + 2 * pad, rotated.height + 2 * pad), (0, 0, 0, 0))
    alpha = Image.new("L", shadow.size, 0)
    alpha.paste(rotated.getchannel("A").point(lambda a: a * 0.35), (pad, pad))
    shadow.putalpha(alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(round(18 * scale)))
    x = (size - rotated.width) // 2
    y = (size - rotated.height) // 2
    shadow_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_layer.paste(shadow, (x - pad, y - pad + round(16 * scale)))
    # Keep the shadow inside the tile.
    clipped = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    clipped.paste(shadow_layer, (0, 0), mask)
    icon.alpha_composite(clipped)
    icon.alpha_composite(rotated, (x, y))
    return icon


def build_icns(target: Path) -> bool:
    """Write an .icns with every standard size. Returns False if iconutil is unavailable."""
    if shutil.which("iconutil") is None:
        return False
    master = draw_icon(1024)
    with tempfile.TemporaryDirectory() as temp:
        iconset = Path(temp) / "AppIcon.iconset"
        iconset.mkdir()
        for size in ICON_SIZES:
            image = master.resize((size, size), Image.Resampling.LANCZOS)
            if size <= 512:
                image.save(iconset / f"icon_{size}x{size}.png")
            if size >= 32:
                image.save(iconset / f"icon_{size // 2}x{size // 2}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(target)], check=True)
    return True


def launcher_script(python: Path, app: Path) -> str:
    log_dir = '"$HOME/.on_this_day_photo_viewer"'
    message = (f'display alert "On This Day can\'t start" message '
               f'"The project or its virtual environment was not found at {PROJECT}. '
               f'Re-run tools/make_launcher.py from the project folder."')
    return f"""#!/bin/sh
# Generated by tools/make_launcher.py. Runs the On This Day project with its virtual environment.
PYTHON={shlex.quote(str(python))}
APP={shlex.quote(str(app))}
if [ ! -x "$PYTHON" ] || [ ! -f "$APP" ]; then
    /usr/bin/osascript -e {shlex.quote(message)}
    exit 1
fi
mkdir -p {log_dir}
cd {shlex.quote(str(app.parent))} || exit 1
exec "$PYTHON" "$APP" >>{log_dir}/launcher.log 2>&1
"""


def build(output_dir: Path) -> Path:
    python = PROJECT / ".venv" / "bin" / "python"
    app = PROJECT / "app.py"
    if not python.exists():
        sys.exit(f"No virtual environment at {python}. Create it first (see README).")

    bundle = output_dir / f"{APP_NAME}.app"
    if bundle.exists():
        shutil.rmtree(bundle)
    contents = bundle / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "Resources").mkdir()

    executable = contents / "MacOS" / EXECUTABLE
    executable.write_text(launcher_script(python, app), encoding="utf-8")
    executable.chmod(0o755)

    info = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": EXECUTABLE,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
    }
    if build_icns(contents / "Resources" / "AppIcon.icns"):
        info["CFBundleIconFile"] = "AppIcon"
    with open(contents / "Info.plist", "wb") as handle:
        plistlib.dump(info, handle)
    return bundle


def install(bundle: Path, applications: Path) -> Path:
    """Copy into an Applications folder, replacing only an earlier copy of this launcher."""
    applications.mkdir(exist_ok=True)
    target = applications / bundle.name
    if target.exists():
        try:
            with open(target / "Contents" / "Info.plist", "rb") as handle:
                existing = plistlib.load(handle).get("CFBundleIdentifier")
        except (OSError, plistlib.InvalidFileException):
            existing = None
        if existing != BUNDLE_ID:
            sys.exit(f"{target} exists and isn't this launcher; not replacing it.")
        shutil.rmtree(target)
    shutil.copytree(bundle, target, symlinks=True)
    # Nudge Finder and the Dock to pick up the (new) icon.
    target.touch()
    return target


def main() -> None:
    if sys.platform != "darwin":
        sys.exit("The launcher is for macOS. On other systems, run: python app.py")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-install", action="store_true", help="don't copy the app into an Applications folder")
    parser.add_argument("--user", action="store_true", help="install in ~/Applications instead of /Applications")
    args = parser.parse_args()
    bundle = build(PROJECT / "dist")
    print(f"Built {bundle}")
    if not args.no_install:
        applications = Path.home() / "Applications" if args.user else Path("/Applications")
        try:
            print(f"Installed {install(bundle, applications)}")
        except PermissionError:
            sys.exit(f"No permission to write to {applications}. Try: python tools/make_launcher.py --user")


if __name__ == "__main__":
    main()
