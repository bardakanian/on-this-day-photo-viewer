"""Regenerate the README screenshots from a synthetic demo library.

    python tools/make_screenshots.py

Runs the real app headless (Qt's "offscreen" platform) against a temporary library of
procedurally drawn landscapes, so the images contain no personal photos, paths or metadata.
Output goes to assets/screenshots/.
"""

import os
import random
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT / "assets" / "screenshots"
WINDOW_SIZE = (1440, 900)
DEMO_DAY = (4, 18)  # the day the gallery shows, so the pictures are reproducible
LIBRARY_NAME = "Demo Library"

# App data lives in a throwaway home, set before the app's constants are imported. The library
# sits at a short, obviously made-up path, since the viewer's Info panel shows the full path.
WORK = Path(tempfile.mkdtemp(prefix="onthisday-shots-"))
DEMO_ROOT = Path("/tmp/on-this-day-demo") if os.name != "nt" else WORK / "demo"
os.environ["HOME"] = os.environ["USERPROFILE"] = str(WORK)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(PROJECT))

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

PHOTOS = {
    "Coastal Walks": ["harbor-sunrise", "quiet-cove", "blue-hour-path", "lake-reflections", "evening-pier",
                      "low-tide", "north-shore", "driftwood", "sea-grass", "slow-water", "headland",
                      "boathouse", "grey-morning", "tern-island", "shingle-beach", "calm-bay",
                      "first-light", "wind-rows", "far-rocks", "salt-marsh", "old-jetty", "spray"],
    "Garden Studies": ["morning-greenhouse", "ridge-and-water", "fern-study", "long-grass", "orchard-light",
                       "stone-wall", "first-frost", "hedgerow", "seed-heads", "glasshouse", "espalier",
                       "rain-shadow", "kitchen-garden", "pollen", "brick-path", "late-roses",
                       "compost-corner", "allotment", "fruit-cage", "leaf-litter", "nettles", "dew"],
    "Short Films": ["sunset-overlook", "morning-tide", "harbor-lights"],
    "Clips": ["garden-breeze", "cloud-study", "quiet-water"],
}
SKIES = [((255, 214, 170), (122, 158, 190)), ((188, 214, 240), (92, 128, 170)), ((255, 198, 170), (120, 110, 160)),
         ((214, 230, 236), (110, 150, 160)), ((250, 226, 180), (150, 170, 190))]


def draw_landscape(width: int, height: int, seed: int) -> Image.Image:
    """A made-up view: gradient sky, a sun, conifers on a ridge, and water."""
    rng = random.Random(seed)
    top, bottom = rng.choice(SKIES)
    image = Image.new("RGB", (width, height))
    canvas = ImageDraw.Draw(image)
    horizon = int(height * rng.uniform(0.58, 0.72))
    for y in range(height):
        shade = y / max(1, horizon) if y < horizon else 1.0
        canvas.line([(0, y), (width, y)], fill=tuple(round(a + (b - a) * min(1.0, shade)) for a, b in zip(top, bottom)))
    sun = int(min(width, height) * 0.09)
    sun_x, sun_y = int(width * rng.uniform(0.25, 0.75)), int(horizon * rng.uniform(0.25, 0.55))
    canvas.ellipse([sun_x - sun, sun_y - sun, sun_x + sun, sun_y + sun], fill=(255, 236, 186))
    water = (58, 96, 110)
    canvas.rectangle([0, horizon, width, height], fill=water)
    tree = (46, 76, 82)
    for index in range(rng.randint(9, 16)):
        base = int(index * width / rng.randint(9, 16) + rng.uniform(-20, 20))
        size = int(height * rng.uniform(0.10, 0.22))
        canvas.polygon([(base - size // 2, horizon), (base, horizon - size), (base + size // 2, horizon)], fill=tree)
    for _ in range(rng.randint(6, 12)):  # ripples
        y = rng.randint(horizon + 6, height - 4)
        length = rng.randint(width // 12, width // 3)
        x = rng.randint(0, max(1, width - length))
        canvas.line([(x, y), (x + length, y)], fill=(210, 225, 230), width=max(1, height // 260))
    return image.filter(ImageFilter.GaussianBlur(max(1, width // 900)))


def build_library(root: Path) -> None:
    """Photos and videos named and dated as a demo, all on the same calendar day in different years."""
    import subprocess

    from onthisday.core import media

    month, day = DEMO_DAY
    seed = 0
    for folder_name, names in PHOTOS.items():
        folder = root / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        videos = folder_name in {"Short Films", "Clips"}
        for name in names:
            seed += 1
            year = 2019 + seed % 7
            taken = datetime(year, month, day, 6 + seed % 14, (seed * 7) % 60)
            if videos:
                clip = folder / f"{name}{'.mov' if seed % 2 else '.mp4'}"
                frame = root / "frame.png"
                draw_landscape(1280, 720, seed).save(frame)
                subprocess.run([
                    media.imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loop", "1", "-i", str(frame),
                    "-t", "1", "-pix_fmt", "yuv420p",
                    "-metadata", f"creation_time={taken:%Y-%m-%dT%H:%M:%S}", str(clip),
                ], capture_output=True, check=True)
                frame.unlink()
                continue
            width, height = (2400, 1800) if seed % 3 else (1800, 2400)
            picture = draw_landscape(width, height, seed)
            exif = Image.Exif()
            exif.get_ifd(0x8769)[36867] = f"{taken:%Y:%m:%d %H:%M:%S}"
            picture.save(folder / f"{name}.png", exif=exif.tobytes())


def capture(window, app, name: str) -> None:
    app.processEvents()
    window.grab().save(str(OUTPUT / f"{name}.png"))
    print(f"Wrote {OUTPUT / name}.png")


def main() -> int:
    import json
    import shutil

    library = DEMO_ROOT / LIBRARY_NAME
    shutil.rmtree(DEMO_ROOT, ignore_errors=True)  # the tool owns this folder; start clean
    build_library(library)
    app_dir = WORK / ".on_this_day_photo_viewer"
    app_dir.mkdir(parents=True, exist_ok=True)
    # A relative folder keeps real paths out of the status bar; the app resolves it from here.
    (app_dir / "config.json").write_text(json.dumps({"photo_folder": str(library), "theme": "light"}))

    sys.argv = ["app"]
    import app as application
    from onthisday.ui.main_window import MainWindow

    application.quiet_qt_logging()
    qt_app = QApplication(sys.argv)
    qt_app.setStyle("Fusion")
    window = MainWindow(qt_app)
    window.resize(*WINDOW_SIZE)
    window.show()
    OUTPUT.mkdir(parents=True, exist_ok=True)

    def wait_for_scan(then) -> None:
        if window.scan_running() or window.saving_previews():
            QTimer.singleShot(200, lambda: wait_for_scan(then))
            return
        then()

    def shoot() -> None:
        window.current_date = date(date.today().year, *DEMO_DAY)
        window.refresh_gallery()
        QTimer.singleShot(1200, gallery)

    def gallery() -> None:
        window.status.setText(f"Library ready  ·  {len(window.gallery.records)} demo items")
        window.folder_status.setText(LIBRARY_NAME)
        capture(window, qt_app, "gallery")
        window.show_videos()
        QTimer.singleShot(800, videos)

    def videos() -> None:
        window.status.setText("Showing fictional demo videos")
        capture(window, qt_app, "video-library")
        window.show_insights()
        # The chart is laid out when its page is resized, which is after the figures arrive.
        QTimer.singleShot(1500, lambda: (window.resize(WINDOW_SIZE[0] - 1, WINDOW_SIZE[1]),
                                         window.resize(*WINDOW_SIZE), QTimer.singleShot(600, insights)))

    def insights() -> None:
        window.status.setText("Library Insights from fictional demo data")
        capture(window, qt_app, "library-insights")
        window.show_gallery()
        photo = next(record for record in window.gallery.records if not record.is_video)
        window._open_from_gallery(photo)
        window.viewer.info_button.setChecked(True)
        QTimer.singleShot(2500, viewer)

    def viewer() -> None:
        window.status.setText("Viewing a fictional demo photo")
        capture(window, qt_app, "viewer")
        window.viewer.close_viewer()
        QTimer.singleShot(400, settings)

    def settings() -> None:
        from onthisday.core.preview_cache import cache_usage
        from onthisday.ui.dialogs import PreferencesDialog

        dialog = PreferencesDialog(window.settings.theme, window.settings.save_previews,
                                   window.settings.time_format, window,
                                   auto_rescan=window.settings.auto_rescan,
                                   preview_quality=window.settings.preview_quality)
        dialog.set_cache_usage(cache_usage())
        dialog.show()
        qt_app.processEvents()
        dialog.grab().save(str(OUTPUT / "settings.png"))
        print(f"Wrote {OUTPUT / 'settings.png'}")
        dialog.close()
        window.close()
        qt_app.quit()

    QTimer.singleShot(300, window.start_indexing)
    QTimer.singleShot(1000, lambda: wait_for_scan(shoot))
    return qt_app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
