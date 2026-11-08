"""Details about one photo or video for the viewer's Info panel. Reads files, so call it off the UI thread."""

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

from . import media
from .timeformat import DEFAULT_TIME_FORMAT, format_capture

_DATE_SOURCES = {
    media.DATE_SPOTLIGHT: "Spotlight (macOS)",
    media.DATE_FILE: "File dates (no date in the file)",
}
# Pillow format names as people know them. MPO is the multi-picture JPEG some cameras write.
_IMAGE_FORMATS = {"MPO": "JPEG", "HEIF": "HEIC"}
_VIDEO_CODECS = {
    "h264": "H.264", "hevc": "HEVC (H.265)", "prores": "ProRes", "mpeg4": "MPEG-4",
    "mpeg2video": "MPEG-2", "mpeg1video": "MPEG-1", "vp8": "VP8", "vp9": "VP9", "av1": "AV1",
    "mjpeg": "Motion JPEG", "wmv3": "Windows Media Video 9", "vc1": "VC-1", "h263": "H.263",
}


@dataclass(frozen=True, slots=True)
class MediaMetadata:
    path: Path
    media_type: str
    file_size: int | None
    format_name: str | None                # "JPEG", "HEIC", "MOV"
    dimensions: tuple[int, int] | None     # as displayed, rotation applied
    captured_at: datetime | None
    date_source: str | None                # media.DATE_EMBEDDED, DATE_SPOTLIGHT or DATE_FILE
    duration_ms: int | None = None
    frame_rate: float | None = None
    video_codec: str | None = None

    @property
    def is_video(self) -> bool:
        return self.media_type == "video"


@dataclass(frozen=True, slots=True)
class VideoProbe:
    duration_ms: int | None
    dimensions: tuple[int, int] | None
    frame_rate: float | None
    codec: str | None


def parse_ffmpeg_probe(output: str) -> VideoProbe:
    """Duration and the first real video stream's size, frame rate and codec from `ffmpeg -i` output."""
    duration = None
    match = re.search(r"Duration: (\d+):(\d{2}):(\d{2}(?:\.\d+)?)", output)
    if match:
        hours, minutes, seconds = match.groups()
        duration = round((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000)
    dimensions = frame_rate = codec = None
    lines = output.splitlines()
    for number, line in enumerate(lines):
        stream = re.search(r"Stream #\d+:\d+.*?: Video: (\w+)(.*)", line)
        if not stream or "(attached pic)" in line:  # skip cover art
            continue
        codec, details = stream.groups()
        size = re.search(r"\b(\d{2,5})x(\d{2,5})\b", details)
        if size:
            dimensions = int(size.group(1)), int(size.group(2))
        rate = re.search(r"([\d.]+) fps", details)
        if rate:
            frame_rate = float(rate.group(1))
        # Phones record sideways and store a rotation; the picture is shown turned upright.
        for following in lines[number + 1:]:
            if re.search(r"Stream #\d+:\d+", following):
                break
            rotation = re.search(r"rotation of (-?[\d.]+) degrees", following)
            if rotation and dimensions and round(abs(float(rotation.group(1)))) % 180 == 90:
                dimensions = dimensions[1], dimensions[0]
        break
    return VideoProbe(duration, dimensions, frame_rate, codec)


def probe_video(path: Path) -> VideoProbe | None:
    if not media.FFMPEG_ENABLED:
        return None
    try:
        result = subprocess.run(
            [media.imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, timeout=10, check=False, creationflags=media._NO_CONSOLE,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_ffmpeg_probe(result.stderr)


def _image_format(path: Path) -> str | None:
    try:
        with Image.open(path) as image:
            name = image.format
    except (OSError, ValueError, TypeError):
        return None
    return _IMAGE_FORMATS.get(name, name) if name else None


def read_metadata(path: Path, media_type: str) -> MediaMetadata:
    try:
        file_size = path.stat().st_size
    except OSError:
        file_size = None
    captured_at, date_source = media.capture_date_with_source(path, media_type)
    if media_type == "video":
        probe = probe_video(path)
        return MediaMetadata(
            path, media_type, file_size, path.suffix.lstrip(".").upper() or None,
            probe.dimensions if probe else None, captured_at, date_source,
            probe.duration_ms if probe else None, probe.frame_rate if probe else None,
            probe.codec if probe else None,
        )
    return MediaMetadata(path, media_type, file_size, _image_format(path), media.display_size(path),
                         captured_at, date_source)


# Formatting for display ------------------------------------------------------------

def format_file_size(size: int) -> str:
    """Decimal units, as Finder and Windows Explorer's details show them: 2.4 MB."""
    if size < 1000:
        return f"{size} bytes" if size != 1 else "1 byte"
    value = float(size)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1000
        if value < 999.5 or unit == "TB":
            return f"{value:.1f} {unit}" if value < 100 else f"{value:.0f} {unit}"
    raise AssertionError("unreachable")


def format_frame_rate(rate: float) -> str:
    return f"{rate:.0f} fps" if abs(rate - round(rate)) < 0.005 else f"{rate:.2f} fps"


def date_source_label(metadata: MediaMetadata) -> str | None:
    if metadata.date_source == media.DATE_EMBEDDED:
        return "Video metadata" if metadata.is_video else "Photo metadata (EXIF)"
    return _DATE_SOURCES.get(metadata.date_source)


def metadata_rows(metadata: MediaMetadata, time_format: str = DEFAULT_TIME_FORMAT) -> list[tuple[str, str]]:
    """(label, value) pairs for the Info panel, in display order; unknown values are left out."""
    rows = [("Date recorded" if metadata.is_video else "Date taken",
             format_capture(metadata.captured_at, time_format) if metadata.captured_at else "Unknown")]
    source = date_source_label(metadata)
    if source:
        rows.append(("Date from", source))
    if metadata.dimensions:
        width, height = metadata.dimensions
        text = f"{width:,} × {height:,}"
        if not metadata.is_video:
            text += f"  ({width * height / 1e6:.1f} MP)"
        rows.append(("Dimensions", text))
    if metadata.duration_ms is not None:
        rows.append(("Duration", media.format_duration(metadata.duration_ms)))
    if metadata.frame_rate:
        rows.append(("Frame rate", format_frame_rate(metadata.frame_rate)))
    if metadata.video_codec:
        rows.append(("Codec", _VIDEO_CODECS.get(metadata.video_codec, metadata.video_codec.upper())))
    if metadata.format_name:
        rows.append(("Type", f"{metadata.format_name} {'video' if metadata.is_video else 'image'}"))
    if metadata.file_size is not None:
        rows.append(("File size", format_file_size(metadata.file_size)))
    rows.append(("Path", str(metadata.path)))
    return rows
