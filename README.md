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
python main.py
python main.py --start-date 2025-09-23 --end-date 2025-09-30
```

## License

MIT