# On This Day

A privacy-friendly macOS desktop app for rediscovering photos and videos captured on the same calendar day in years past.

The current version replaces the original Tkinter prototype with a polished, modular PySide6 interface while preserving the existing media index, thumbnail cache, and saved library settings.

## Highlights

- Recursively indexes a local folder of photos and videos
- Groups matches by capture year for the selected month and day
- Switches between all media, photos only, and videos only
- Moves to the previous day, next day, or today
- Displays a responsive thumbnail gallery with collapsible year sections
- Loads large year groups in batches to keep the interface responsive
- Includes a searchable, sortable video library
- Provides folder-specific Library Insights without rescanning the filesystem
- Opens media in the operating system's default application
- Supports system, light, and dark appearance modes
- Runs indexing and thumbnail generation away from the main interface
- Reuses cached records for unchanged files and removes stale index entries
- Stores all application data locally

## What's new

- Rebuilt desktop interface using PySide6 and the Qt Fusion style
- Modular source layout for core indexing, storage, media handling, themes, pages, dialogs, and reusable widgets
- Live scan progress showing checked, updated, and cached items
- Improved empty states, status messages, error dialogs, and application logging
- Searchable table view for all indexed videos
- Library Insights dashboard with totals, busiest day, largest year, most active month, and a media-by-year chart
- Theme preference with system, light, and dark options
- Compatibility with the existing `~/.on_this_day_photo_viewer` data directory and thumbnail signature
- Basic automated coverage for settings, database filtering, and indexing

## Requirements

- Python 3.10 or newer
- macOS for the primary supported desktop experience
- Read access to the folder containing your media

Python dependencies are installed from `requirements.txt`:

- PySide6
- Pillow
- pillow-heif
- imageio-ffmpeg

`pillow-heif` enables HEIC/HEIF files. `imageio-ffmpeg` supplies FFmpeg support for video metadata and thumbnails. The app still starts if either optional capability is unavailable, but the related media features are limited.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/bardakanian/on-this-day-photo-viewer.git
cd on-this-day-photo-viewer
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Run the app

```bash
python app.py
```

On first launch, choose the folder containing your photos and videos. The initial scan may take time for a large library. Later scans reuse the SQLite index and skip unchanged files.

## Using the app

The main gallery shows media captured on the selected month and day, organized into year sections from newest to oldest.

- Use **Choose Folder** to select or change the media library.
- Use **Rescan** after adding, removing, or editing files.
- Use the date controls to browse adjacent calendar days or return to today.
- Use the media filter to show all items, photos, or videos.
- Select **Video Library** to search and sort every indexed video.
- Select **Library Insights** to explore analytics for the current media folder.
- Double-click a gallery item or video row to open it in the default application.
- Open **Settings** to follow the system appearance or choose light or dark mode.

## Library Insights

Open **Library Insights** from the toolbar or the **View** menu to analyze the currently selected media folder using the existing SQLite index. No filesystem rescan is required.

The page shows:

- Total indexed photos, videos, and combined media
- The busiest calendar day across all capture years, including February 29
- The capture year containing the most indexed media
- A chronological stacked bar chart with separate photo and video counts by year and exact hover values
- The most active calendar month across all capture years

Records missing date components are excluded only from the relevant date-based calculation and still count toward the library totals. Ties select the earliest calendar day, year, or month.

## Keyboard shortcuts

On macOS, Qt displays the Control shortcuts below using the Command key where appropriate.

| Action | Shortcut |
| --- | --- |
| Choose media folder | `⌘O` |
| Rescan library | `⌘R` |
| Previous day | `⌘←` |
| Next day | `⌘→` |
| Go to today | `⌘T` |
| Open video library | `⌘⇧V` |
| Open Library Insights | `⌘⇧I` |
| Search videos | `⌘F` |
| Open settings | `⌘,` |
| Close window | `⌘W` |

## Supported media

**Images:** JPG, JPEG, PNG, TIFF, BMP, GIF, WebP, HEIC, and HEIF.

**Videos:** MOV, MP4, M4V, AVI, MKV, WMV, MPEG, MPG, and 3GP.

Capture dates are determined from image EXIF data or embedded video metadata when available. On macOS, Spotlight metadata is also checked. Filesystem creation or modification timestamps provide fallbacks.

## Local data and privacy

Media processing stays on your computer. The app has no analytics, advertising, account sign-in, or cloud upload functionality.

Application data is stored in:

```text
~/.on_this_day_photo_viewer/
├── config.json
├── on_this_day.log
├── photo_index.sqlite3
└── thumbnails/
```

This directory can contain absolute paths from your media library and should not be committed to source control. The app reads and opens source media; it does not intentionally modify the selected files.

## Project structure

```text
app.py                    Compatibility entry point and application startup
onthisday/
├── core/                 Settings, SQLite storage, indexing, and media metadata
└── ui/
    ├── pages/            Gallery, video library, and Library Insights
    ├── theme/            Colors, metrics, typography, and stylesheets
    └── widgets/          Flow layout, media cards, and shared controls
tests/                    Core storage and indexing tests
```

## Development

Run the test suite from the project root:

```bash
python -m unittest discover -s tests
```

The application writes unexpected errors to `~/.on_this_day_photo_viewer/on_this_day.log`.

## Project status

Active development. Test with a backed-up media library and review detected capture dates before relying on the index for organization decisions.
