#!/usr/bin/env python3
"""
MIT License

Copyright (c) 2025

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

INDEX:
  1. Load environment variables ...................... Line 56
  2. Parse command line arguments .................... Line 59
  3. Format dates .................................... Line 73
  4. Fetch bookmarks from Karakeep API ............... Line 78
  5. Save raw response ............................... Line 84
  6. Extract bookmarks ............................... Line 87
  7. Filter bookmarks by date range .................. Line 90
  8. Extract URLs from filtered bookmarks ............ Line 96
  9. Create downloads directory ...................... Line 106
 10. Download videos using yt-dlp .................... Line 109
 11. Filter videos by duration (max 3 min) ........... Line 118
 12. Create file list for ffmpeg ..................... Line 137
 13. Create compilation directory .................... Line 140
 14. Compile videos using ffmpeg ..................... Line 143
 15. Generate bookmark report ........................ Line 163
"""

import os
import re
import subprocess
import requests
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from jinja2 import Template

# Load environment variables
load_dotenv()

# Parse command line arguments
parser = argparse.ArgumentParser()
parser.add_argument(
    '--start-date',
    type=str,
    default=(datetime.now() - timedelta(days=7)).isoformat()
)
parser.add_argument(
    '--end-date',
    type=str,
    default=datetime.now().isoformat()
)
parser.add_argument(
    '--merge-only',
    action='store_true',
    help='Skip download steps and go directly to merging existing videos'
)
parser.add_argument(
    '--tiktok',
    action='store_true',
    help='Generate video in TikTok format (1080x1920 portrait)'
)
args = parser.parse_args()

# Format dates
formatted_end_date = datetime.fromisoformat(args.end_date).strftime('%Y_%m_%d')

# Set video dimensions based on platform
width, height = (1080, 1920) if args.tiktok else (1920, 1080)

if not args.merge_only:
    start_ts = datetime.fromisoformat(args.start_date).timestamp() * 1000
    end_ts = datetime.fromisoformat(args.end_date).timestamp() * 1000

    # Fetch bookmarks from Karakeep API
    response = requests.get(
        f"{os.getenv('KARAKEEP_BASE_URL')}/api/v1/lists/{os.getenv('KARAKEEP_LIST_ID')}/bookmarks",
        headers={'Authorization': f"Bearer {os.getenv('KARAKEEP_API_KEY')}"}
    ).json()

    # Save raw response
    Path('karakeep_response.json').write_text(__import__('json').dumps(response, indent=2))

    # Extract bookmarks
    bookmarks = response.get('bookmarks', [])

    # Filter bookmarks by date range
    filtered_bookmarks = [
        b for b in bookmarks
        if start_ts <= datetime.fromisoformat(b['createdAt'].replace('Z', '+00:00')).timestamp() * 1000 <= end_ts
    ]

    # Extract URLs from filtered bookmarks
    urls = [
        u for b in bookmarks
        if start_ts <= datetime.fromisoformat(b['createdAt'].replace('Z', '+00:00')).timestamp() * 1000 <= end_ts
        for u in re.findall(
            r'https?://\S+',
            b.get('content', {}).get('url', '') + ' ' + (b.get('title') or '')
        )
    ]

    # Create downloads directory
    Path(f'downloads/{formatted_end_date}').mkdir(parents=True, exist_ok=True)

    # Download videos using yt-dlp
    for url in urls:
        subprocess.run([
            'yt-dlp',
            '--cookies-from-browser', 'firefox',
            '-o', f'downloads/{formatted_end_date}/%(id)s.%(ext)s',
            url
        ])

    # Get all downloaded files and filter by duration (max 3 minutes)
    all_files = sorted(Path(f'downloads/{formatted_end_date}').glob('*'))
    files = []
    for f in all_files:
        result = subprocess.run([
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            str(f)
        ], capture_output=True, text=True)
        try:
            duration = float(result.stdout.strip())
            if duration <= 180:  # 3 minutes = 180 seconds
                files.append(f)
            else:
                f.unlink()  # Delete videos longer than 3 minutes
        except (ValueError, AttributeError):
            files.append(f)  # Keep if duration can't be determined
else:
    # Skip to merging: use existing files in downloads directory
    files = sorted(Path(f'downloads/{formatted_end_date}').glob('*'))
    filtered_bookmarks = []

# Re-encode all videos to uniform format (H.264/AAC/MP4) with consistent dimensions
normalized_files = []
for idx, f in enumerate(files):
    normalized_path = Path(f'temp_normalized_{idx}.mp4')
    if not normalized_path.exists():
        subprocess.run([
            'ffmpeg',
            '-i', str(f),
            '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2',
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-preset', 'fast',
            '-crf', '23',
            '-r', '30',
            '-y',
            str(normalized_path)
        ])
    normalized_files.append(normalized_path)

# Create file list for ffmpeg using normalized files
Path('filelist.txt').write_text('\n'.join(
    f"file '{str(f.resolve()).replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'"
    for f in normalized_files
))

# Create compilation directory
Path('compilation').mkdir(exist_ok=True)

# Compile videos using ffmpeg
subprocess.run([
    'ffmpeg',
    '-f', 'concat',
    '-safe', '0',
    '-vsync', 'cfr',
    '-i', 'filelist.txt',
    '-c:v', 'libx264',
    '-preset', 'fast',
    '-crf', '23',
    '-c:a', 'aac',
    '-b:a', '128k',
    '-r', '30',
    '-g', '30',
    '-async', '1',
    '-avoid_negative_ts', 'make_zero',
    '-fflags', '+genpts',
    '-movflags', '+faststart',
    '-y',
    f'compilation/{formatted_end_date}.mp4'
])

# Clean up temporary normalized files
for f in normalized_files:
    f.unlink()

# Generate bookmark report
template = Template(Path('templates/bookmark_report.md.j2').read_text())
report = template.render(
    start_date=args.start_date,
    end_date=args.end_date,
    bookmarks=filtered_bookmarks
)
Path(f'compilation/{formatted_end_date}.md').write_text(report)