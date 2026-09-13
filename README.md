# On This Day Photo Viewer

A privacy-friendly, cross-platform Python desktop application that resurfaces photos and videos captured on the same calendar day across different years.

Built and iterated through AI-assisted vibe coding, with hands-on testing and refinement on both Windows and macOS.

## Why I built it

Large personal media libraries make it difficult to rediscover older moments. This application turns an ordinary local photo folder into an "on this day" experience without uploading personal media to a cloud service.

## Features

- Recursively indexes photos and videos from a folder you choose
- Groups matching media by capture year for the selected month and day
- Reads image EXIF dates and video metadata, with platform-aware fallbacks
- Supports common image formats plus HEIC/HEIF when `pillow-heif` is installed
- Generates and caches thumbnails for responsive browsing
- Uses SQLite to avoid re-indexing unchanged files
- Runs indexing and thumbnail work in the background to keep the interface responsive
- Filters results by photos, videos, or all media
- Navigates to previous, current, and next calendar days
- Expands large year groups incrementally with "load more" behavior
- Includes a searchable video index viewer
- Opens selected media in the operating system's default application
- Stores its index, thumbnails, and preferences locally

## Technology

- Python
- Tkinter / ttk
- Pillow
- pillow-heif
- imageio-ffmpeg
- SQLite
- Threading and `ThreadPoolExecutor`

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/bardakanian/on-this-day-photo-viewer.git
cd on-this-day-photo-viewer
```

### 2. Create a virtual environment

macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Run the application

```bash
python app.py
```

On first launch, choose the local folder containing your media. Initial indexing time depends on the size of the library. Later scans reuse the SQLite index and cached thumbnails.

## Supported media

Images: JPG, JPEG, PNG, TIFF, BMP, GIF, WebP, HEIC, and HEIF.

Videos: MOV, MP4, M4V, AVI, MKV, WMV, MPEG, MPG, and 3GP.

## Privacy

The application processes media locally. It does not contain analytics, advertising, account sign-in, or cloud-upload functionality.

Local application data is stored in:

```text
~/.on_this_day_photo_viewer/
```

That directory may contain absolute paths from the selected media library and should never be committed to source control.

## Cross-platform notes

- macOS can use Spotlight metadata as an additional capture-date source.
- Windows uses available embedded metadata and filesystem timestamps as fallbacks.
- Opening a media item uses the native operating-system command.
- Video thumbnails and metadata depend on the FFmpeg binary supplied by `imageio-ffmpeg`.

## Development approach

This project began as an AI-assisted vibe-coding experiment. I directed the feature design, refined prompts, tested the generated behavior, debugged platform differences, and iterated on indexing, caching, date detection, and interface responsiveness.

The current implementation is intentionally maintained as a single-file prototype. A future version could separate indexing, metadata extraction, persistence, thumbnail generation, and interface code into individual modules.

## Roadmap

- Package native installers for Windows and macOS
- Add automated tests for capture-date fallbacks
- Split the application into focused modules
- Add configurable thumbnail sizes and gallery columns
- Improve duplicate detection and index diagnostics

## Project status

Active prototype. Test with a backed-up media library and review detected dates before relying on the index for organization decisions. The application reads and opens source media; it does not intentionally modify the selected media files.

