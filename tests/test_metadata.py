"""The viewer's Info panel data: reading and formatting a file's details."""

import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from onthisday.core import media, metadata
from onthisday.core.metadata import MediaMetadata, format_file_size, metadata_rows, parse_ffmpeg_probe

IPHONE_PROBE = """\
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'IMG_0001.MOV':
  Duration: 00:01:05.53, start: 0.000000, bitrate: 15873 kb/s
  Stream #0:0[0x1](und): Video: hevc (Main) (hvc1 / 0x31637668), yuv420p(tv, bt709), 1920x1080, 15675 kb/s, 29.98 fps, 30 tbr, 600 tbn (default)
      Metadata:
        handler_name    : Core Media Video
      Side data:
        displaymatrix: rotation of -90.00 degrees
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, mono, fltp, 94 kb/s (default)
"""


class ProbeParsingTests(unittest.TestCase):
    def test_portrait_iphone_video(self):
        probe = parse_ffmpeg_probe(IPHONE_PROBE)
        self.assertEqual(probe.duration_ms, 65530)
        self.assertEqual(probe.dimensions, (1080, 1920))  # recorded sideways, shown upright
        self.assertEqual(probe.frame_rate, 29.98)
        self.assertEqual(probe.codec, "hevc")

    def test_cover_art_is_not_the_video(self):
        output = (
            "  Duration: 00:00:10.00, start: 0.000000\n"
            "  Stream #0:0: Video: mjpeg (Baseline), yuvj420p, 600x600, 90k tbn (attached pic)\n"
            "  Stream #0:1: Video: h264 (High), yuv420p, 1280x720, 25 fps, 25 tbr\n"
        )
        probe = parse_ffmpeg_probe(output)
        self.assertEqual((probe.codec, probe.dimensions, probe.frame_rate), ("h264", (1280, 720), 25.0))

    def test_unreadable_output(self):
        probe = parse_ffmpeg_probe("IMG.MOV: Invalid data found when processing input")
        self.assertEqual(probe, metadata.VideoProbe(None, None, None, None))


class FormattingTests(unittest.TestCase):
    def test_file_sizes(self):
        cases = {0: "0 bytes", 1: "1 byte", 999: "999 bytes", 1000: "1.0 KB", 2_400_000: "2.4 MB",
                 999_600: "1.0 MB", 152_000_000: "152 MB", 3_100_000_000: "3.1 GB"}
        for size, expected in cases.items():
            self.assertEqual(format_file_size(size), expected, size)

    def test_photo_rows(self):
        info = MediaMetadata(Path("/Pictures/IMG_1.jpg"), "image", 2_400_000, "JPEG", (4032, 3024),
                             datetime(2015, 7, 4, 9, 5), media.DATE_EMBEDDED)
        self.assertEqual(metadata_rows(info), [
            ("Date taken", "July 4, 2015  •  09:05"),
            ("Date from", "Photo metadata (EXIF)"),
            ("Dimensions", "4,032 × 3,024  (12.2 MP)"),
            ("Type", "JPEG image"),
            ("File size", "2.4 MB"),
            ("Path", str(Path("/Pictures/IMG_1.jpg"))),
        ])

    def test_video_rows_and_unknown_values(self):
        info = MediaMetadata(Path("/v/clip.mov"), "video", 15_000_000, "MOV", (1080, 1920), None, None,
                             65530, 29.97, "hevc")
        rows = dict(metadata_rows(info))
        self.assertEqual(rows["Date recorded"], "Unknown")
        self.assertNotIn("Date from", rows)
        self.assertEqual(rows["Dimensions"], "1,080 × 1,920")
        self.assertEqual((rows["Duration"], rows["Frame rate"], rows["Codec"]), ("1:06", "29.97 fps", "HEVC (H.265)"))
        self.assertEqual(rows["Type"], "MOV video")


class ReadMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_photo(self):
        path = self.root / "rotated.jpg"
        exif = Image.Exif()
        exif[0x0112] = 6  # shown rotated 90°
        exif.get_ifd(0x8769)[36867] = "2015:07:04 12:00:00"
        Image.new("RGB", (400, 300), "red").save(path, exif=exif.tobytes())
        info = metadata.read_metadata(path, "image")
        self.assertEqual(info.captured_at, datetime(2015, 7, 4, 12))
        self.assertEqual(info.date_source, media.DATE_EMBEDDED)
        self.assertEqual(info.dimensions, (300, 400))
        self.assertEqual(info.format_name, "JPEG")
        self.assertEqual(info.file_size, path.stat().st_size)

    def test_photo_without_metadata_says_where_its_date_came_from(self):
        path = self.root / "plain.png"
        Image.new("RGB", (8, 8)).save(path)
        with patch.object(media, "parse_macos_metadata_date", return_value=None):
            info = metadata.read_metadata(path, "image")
        self.assertEqual(info.date_source, media.DATE_FILE)
        self.assertEqual(dict(metadata_rows(info))["Date from"], "File dates (no date in the file)")

    def test_missing_file(self):
        info = metadata.read_metadata(self.root / "gone.jpg", "image")
        self.assertEqual((info.file_size, info.dimensions, info.captured_at), (None, None, None))
        self.assertEqual(dict(metadata_rows(info))["Date taken"], "Unknown")

    @unittest.skipUnless(media.FFMPEG_ENABLED, "ffmpeg not installed")
    def test_video(self):
        path = self.root / "clip.mov"
        subprocess.run([
            media.imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-f", "lavfi", "-i", "testsrc=s=640x360:d=2.5:r=30",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path),
        ], capture_output=True, check=True)
        info = metadata.read_metadata(path, "video")
        self.assertEqual((info.dimensions, info.duration_ms, info.frame_rate, info.video_codec),
                         ((640, 360), 2500, 30.0, "h264"))
        self.assertEqual(info.format_name, "MOV")


if __name__ == "__main__":
    unittest.main()
