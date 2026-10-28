import hashlib
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from PIL import Image, ImageOps

from .constants import LEGACY_THUMBNAIL_SIZE, THUMBNAIL_DIR, THUMBNAIL_SIZE, VIDEO_EXTENSIONS
from .database import ensure_app_dirs

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_ENABLED = True
except ImportError:
    HEIC_ENABLED = False

try:
    import imageio_ffmpeg
    FFMPEG_ENABLED = True
except ImportError:
    imageio_ffmpeg = None
    FFMPEG_ENABLED = False

Image.MAX_IMAGE_PIXELS = None

# On Windows, run ffmpeg without a console window. Otherwise, when the app has no console of
# its own (started from a shortcut with pythonw), one would flash up for every video processed.
_NO_CONSOLE = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def media_type_for_path(path: Path) -> str:
    return "video" if path.suffix.lower() in VIDEO_EXTENSIONS else "image"


# Clocks that were never set, and "zero" timestamps, show up as these dates. They are never real
# capture times; treating them as missing lets the next source of a date be used instead.
_PLACEHOLDER_DAYS = {(1904, 1, 1), (1970, 1, 1), (1980, 1, 1)}


def is_placeholder_date(value: datetime) -> bool:
    """True for epoch and unset-clock dates (checked a day either side to allow for time zones)."""
    if value.year < 1900 or value.year > datetime.now().year + 1:
        return True
    for offset in (-1, 0, 1):
        day = value + timedelta(days=offset)
        if (day.year, day.month, day.day) in _PLACEHOLDER_DAYS:
            return True
    return False


def _usable(value: datetime | None) -> datetime | None:
    return value if value is not None and not is_placeholder_date(value) else None


_SPOTLIGHT_FIELDS = ("kMDItemContentCreationDate", "kMDItemFSCreationDate")
# Spotlight dates within this many seconds of the file's own creation time carry no extra information.
_SAME_MOMENT_SECONDS = 2


def _parse_spotlight_value(value: str) -> datetime | None:
    value = value.strip()
    if not value or value == "(null)":
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z").astimezone().replace(tzinfo=None)
    except ValueError:
        return None


def choose_spotlight_date(content_created: datetime | None, file_created: datetime | None) -> datetime | None:
    """Spotlight's content date, but only when it says more than the file system does.

    For files without embedded dates, Spotlight reports the file's own creation time as the
    content date. That is when the file was copied to this disk (a backup, an export, a
    download), not when the photo was taken, so it must not be used as a capture date.
    """
    if content_created is None:
        return None
    if file_created is not None and abs((content_created - file_created).total_seconds()) <= _SAME_MOMENT_SECONDS:
        return None
    return content_created


def parse_macos_metadata_date(path: Path) -> datetime | None:
    """A capture date Spotlight found inside the file, or None."""
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            ["mdls", "-raw", *(arg for field in _SPOTLIGHT_FIELDS for arg in ("-name", field)), str(path)],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # With -raw, values are separated by NUL characters, in the order requested.
    values = result.stdout.split("\0")
    if len(values) < 2:
        return None
    return choose_spotlight_date(_parse_spotlight_value(values[0]), _parse_spotlight_value(values[1]))


def get_image_exif_date(path: Path) -> datetime | None:
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            for tag in (36867, 36868, 306):
                value = exif.get(tag) if exif else None
                if not value:
                    continue
                if isinstance(value, bytes):
                    value = value.decode("utf-8", errors="ignore")
                for date_format in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                    try:
                        return datetime.strptime(str(value).strip(), date_format)
                    except ValueError:
                        continue
    except (OSError, ValueError, TypeError):
        pass
    return None


def get_video_metadata_date(path: Path) -> datetime | None:
    if not FFMPEG_ENABLED:
        return None
    try:
        result = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, timeout=10, check=False, creationflags=_NO_CONSOLE,
        )
        candidates = []
        for line in result.stderr.splitlines():
            stripped = line.strip()
            if "creation_time" in stripped:
                candidates.append(stripped.partition(":")[2].strip())
            elif "date" in stripped.lower() and ":" in stripped:
                key, _, value = stripped.partition(":")
                if key.strip().lower() in {"date", "date-eng", "creation date"}:
                    candidates.append(value.strip())
        for value in filter(None, candidates):
            normalized = value.replace("Z", "+00:00")
            for parser in (
                datetime.fromisoformat,
                lambda item: datetime.strptime(item, "%Y-%m-%d %H:%M:%S"),
                lambda item: datetime.strptime(item, "%Y/%m/%d %H:%M:%S"),
            ):
                try:
                    parsed = parser(normalized)
                    return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed
                except ValueError:
                    continue
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return None


def get_filesystem_date(path: Path) -> datetime | None:
    """The earlier of the file's creation and modification times.

    Copying a file (to a backup drive, a new Mac, a cloud export) resets its creation time
    to the copy time but keeps its modification time, so the earlier one is closer to when
    the photo or video was actually made.
    """
    try:
        stat = path.stat()
    except OSError:
        return None
    # st_birthtime exists on macOS, and on Windows from Python 3.12; before that Windows
    # reports the creation time as st_ctime (elsewhere st_ctime is the last metadata change).
    created = getattr(stat, "st_birthtime", stat.st_ctime if os.name == "nt" else stat.st_mtime)
    candidates = [datetime.fromtimestamp(stamp) for stamp in (stat.st_mtime, created) if stamp > 0]
    # Ignore zero and unset-clock timestamps some filesystems and memory cards report.
    valid = [value for value in candidates if not is_placeholder_date(value)]
    return min(valid or candidates, default=None)


def get_capture_date(path: Path, media_type: str) -> datetime | None:
    # Embedded date first, then a date Spotlight found in the content, then the file's own times.
    embedded = get_image_exif_date(path) if media_type == "image" else get_video_metadata_date(path)
    return _usable(embedded) or _usable(parse_macos_metadata_date(path)) or get_filesystem_date(path)


def thumbnail_cache_path(
    path: Path, file_size: int, modified_ns: int, size: tuple[int, int] = THUMBNAIL_SIZE,
) -> Path:
    signature = f"{path}|{file_size}|{modified_ns}|{size[0]}x{size[1]}"
    return THUMBNAIL_DIR / f"{hashlib.sha256(signature.encode()).hexdigest()}.jpg"


def legacy_thumbnail_cache_path(path: Path, file_size: int, modified_ns: int) -> Path:
    return thumbnail_cache_path(path, file_size, modified_ns, LEGACY_THUMBNAIL_SIZE)


def _failure_marker(target: Path) -> Path:
    return target.with_suffix(".failed")


def thumbnail_cache_files(path: Path, file_size: int, modified_ns: int) -> list[Path]:
    """Every cache file that may exist for one media item."""
    target = thumbnail_cache_path(path, file_size, modified_ns)
    return [target, _failure_marker(target), legacy_thumbnail_cache_path(path, file_size, modified_ns)]


def _image_thumbnail(source: Path, target: Path) -> None:
    with Image.open(source) as image:
        if getattr(image, "is_animated", False):
            try:
                image.seek(0)
            except EOFError:
                pass
        # Let JPEGs decode at a reduced scale. This must happen before exif_transpose
        # loads the full image; a square request covers both rotated orientations.
        longest = max(THUMBNAIL_SIZE)
        image.draft("RGB", (longest, longest))
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        image.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", THUMBNAIL_SIZE, THUMBNAIL_PADDING)
        canvas.paste(image, ((THUMBNAIL_SIZE[0] - image.width) // 2, (THUMBNAIL_SIZE[1] - image.height) // 2))
        canvas.save(target, "JPEG", quality=87, optimize=True)


def _video_thumbnail(source: Path, target: Path) -> bool:
    # Prefer a frame one second in (skips black fade-ins); clips shorter than that
    # produce nothing, so fall back to the very first frame.
    for seek in (["-ss", "1"], []):
        try:
            subprocess.run([
                imageio_ffmpeg.get_ffmpeg_exe(), "-y", *seek, "-i", str(source),
                "-frames:v", "1", "-vf",
                f"scale={THUMBNAIL_SIZE[0]}:{THUMBNAIL_SIZE[1]}:force_original_aspect_ratio=decrease,"
                f"pad={THUMBNAIL_SIZE[0]}:{THUMBNAIL_SIZE[1]}:(ow-iw)/2:(oh-ih)/2",
                "-q:v", "3", str(target),
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False,
                creationflags=_NO_CONSOLE)
        except (OSError, subprocess.SubprocessError):
            continue
        if target.exists() and target.stat().st_size > 0:
            return True
    return False


def get_cached_thumbnail(path: Path, media_type: str, file_size: int, modified_ns: int) -> Path | None:
    ensure_app_dirs()
    target = thumbnail_cache_path(path, file_size, modified_ns)
    if target.exists():
        return target
    failed = _failure_marker(target)
    if failed.exists():
        return None
    if media_type == "video" and not FFMPEG_ENABLED:
        return None
    try:
        if media_type == "video":
            if not _video_thumbnail(path, target):
                raise OSError("ffmpeg produced no frame")
        else:
            _image_thumbnail(path, target)
        return target
    except (OSError, ValueError):
        try:
            target.unlink(missing_ok=True)
            # Remember the failure so the file isn't re-decoded every time it is shown.
            # Skip this when the source is missing (e.g. an unmounted drive) so it retries later.
            # The cache key includes size and mtime, so editing the file also retries.
            if path.exists():
                failed.touch()
        except OSError:
            pass
        return None


def open_in_default_app(path: Path) -> tuple[bool, str | None]:
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif os.name == "nt":
            os.startfile(str(path))
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True, None
    except OSError as exc:
        return False, str(exc)


def load_display_image(path: Path, max_edge: int) -> Image.Image:
    """Decode a photo for the viewer: EXIF-rotated, at most `max_edge` on its longest side."""
    with Image.open(path) as image:
        if getattr(image, "is_animated", False):
            try:
                image.seek(0)
            except EOFError:
                pass
        image.draft("RGB", (max_edge, max_edge))
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGBA") if image.mode in {"RGBA", "LA", "P"} else image.convert("RGB")
        if max(image.size) > max_edge:
            image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        return image


THUMBNAIL_PADDING = (18, 20, 24)  # canvas colour of photo thumbnails (video ones are padded black)


def letterbox_content_rect(
    width: int, height: int, pixel: Callable[[int, int], tuple[int, int, int]], tolerance: int = 12,
) -> tuple[int, int, int, int] | None:
    """Find the picture inside a padded thumbnail as (x, y, width, height).

    Thumbnails are letterboxed with THUMBNAIL_PADDING, so the picture touches two opposite
    edges and is centred. Only the middle row and column are sampled. Returns None when the
    result isn't believable (e.g. a dark photo whose own edges look like padding).
    """
    def is_padding(x: int, y: int) -> bool:
        return all(abs(a - b) <= tolerance for a, b in zip(pixel(x, y), THUMBNAIL_PADDING))

    def span(length: int, sample: Callable[[int], bool]) -> tuple[int, int]:
        start = 0
        while start < length and sample(start):
            start += 1
        end = length
        while end > start and sample(end - 1):
            end -= 1
        return start, end

    left, right = span(width, lambda x: is_padding(x, height // 2))
    top, bottom = span(height, lambda y: is_padding(width // 2, y))
    content_w, content_h = right - left, bottom - top
    if content_w <= 0 or content_h <= 0:
        return None
    # Padding is on one axis only and equal on both sides (allow a couple of pixels for JPEG noise).
    padded_x, padded_y = width - content_w > 2, height - content_h > 2
    if padded_x and padded_y:
        return None
    if abs(left - (width - right)) > 3 or abs(top - (height - bottom)) > 3:
        return None
    if content_w < width * 0.25 or content_h < height * 0.25:
        return None
    return left, top, content_w, content_h


def format_duration(milliseconds: int) -> str:
    total = max(0, int(round(milliseconds / 1000)))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def display_size(path: Path) -> tuple[int, int] | None:
    """Pixel size of a photo as displayed (EXIF rotation applied), read from the header only."""
    try:
        with Image.open(path) as image:
            width, height = image.size
            orientation = image.getexif().get(0x0112, 1)
    except (OSError, ValueError, TypeError):
        return None
    return (height, width) if orientation in (5, 6, 7, 8) else (width, height)
