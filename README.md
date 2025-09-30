# Quick Compil

Fetch bookmarks from Karakeep, download videos via yt-dlp, compile to single MP4, generate report. Filters videos >3min.

## Prerequisites

- Python 3.7+: `pip install requests python-dotenv jinja2`
- yt-dlp: `pip install yt-dlp`
- FFmpeg: `sudo apt install ffmpeg`
- Karakeep instance with API access

## Setup

```bash
cp .env.example .env
```

Edit `.env`:
```env
KARAKEEP_BASE_URL=http://localhost:3080
KARAKEEP_LIST_ID=your_list_id
KARAKEEP_API_KEY=ak2_xxxxx
```

## Usage

```bash
# Default: last 7 days, YouTube format (1920x1080)
python main.py

# Specific date range
python main.py --start-date 2025-09-23 --end-date 2025-09-30

# Skip download, merge only
python main.py --merge-only --end-date 2025-09-30

# TikTok format (1080x1920 portrait)
python main.py --tiktok

# Combined flags
python main.py --tiktok --merge-only --end-date 2025-09-30
```

## Features

- **Format normalization**: Re-encodes mixed video formats (MP4/WebM) to uniform H.264/AAC
- **Dimension consistency**: Scales videos to fit standard dimensions with letterboxing (no distortion)
- **Platform presets**: YouTube (1920x1080) or TikTok (1080x1920) via `--tiktok` flag
- **Merge-only mode**: Skip downloads, compile existing videos via `--merge-only`
- **Timestamp correction**: Fixes non-monotonic DTS warnings with `-vsync cfr` and `-async 1`
- **Smart caching**: Skips re-encoding if normalized files already exist

## YouTube Publishing

Minimal YouTube uploader in `youtube.py` (104 lines):

```bash
# Setup environment variables
export YOUTUBE_CLIENT_ID="your_client_id"
export YOUTUBE_CLIENT_SECRET="your_secret"
export YOUTUBE_PROJECT_ID="your_project"

# Upload latest compilation
python youtube.py
```

Auto-uploads latest `.mp4` from `compilation/` with matching `.md` description as private video.

## License

MIT