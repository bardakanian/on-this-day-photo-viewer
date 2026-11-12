from pathlib import Path

APP_NAME = "On This Day"
# The one place the version lives. Bump it with every change and add a CHANGELOG.md entry.
VERSION = "1.10.3"
APP_DIR = Path.home() / ".on_this_day_photo_viewer"
CONFIG_FILE = APP_DIR / "config.json"
DB_FILE = APP_DIR / "photo_index.sqlite3"
THUMBNAIL_DIR = APP_DIR / "thumbnails"

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif",
    ".webp", ".heic", ".heif",
}
VIDEO_EXTENSIONS = {
    ".mov", ".mp4", ".m4v", ".avi", ".mkv", ".wmv", ".mpeg",
    ".mpg", ".3gp",
}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
# Rendered at 2x the 248x186 preview so thumbnails stay sharp on Retina displays.
THUMBNAIL_SIZE = (496, 372)
# Older thumbnails are still shown as placeholders while sharper ones are generated.
LEGACY_THUMBNAIL_SIZE = (240, 180)
BATCH_COMMIT_SIZE = 250
# Bump to make the next scan re-read every file's capture date. Despite the name (kept for
# database compatibility) it applies to photos and videos since version 6, which stopped
# dating metadata-less files by when they were copied; 7 ignores epoch and unset-clock dates;
# 8 reads EXIF DateTimeOriginal, which earlier versions missed; 9 keeps a video's QuickTime
# local creation time instead of converting its UTC time with this computer's time zone.
VIDEO_METADATA_VERSION = 9
# Coming back to the app re-checks the library for new and removed files once this much time has passed.
AUTO_RESCAN_SECONDS = 10 * 60
# The window counts as stalled when it doesn't respond for this long (a few dropped frames).
STALL_THRESHOLD_SECONDS = 0.2
# Gaps longer than this are the computer sleeping, not the app stalling.
MAX_STALL_SECONDS = 30.0
# Cap on stalls logged per session, so the log can't grow without bound.
MAX_STALL_REPORTS = 300
