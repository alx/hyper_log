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
  1. Load environment variables ...................... Line 59
  2. Parse command line arguments .................... Line 62
  3. Format dates .................................... Line 86
  4. Fetch bookmarks from Karakeep API ............... Line 96
  5. Save raw response ............................... Line 102
  6. Extract bookmarks ............................... Line 105
  7. Filter bookmarks by date range .................. Line 108
  8. Extract URLs from filtered bookmarks ............ Line 114
  9. Fetch URLs from Matrix room history ............. Line 124
 10. Deduplicate URLs from both sources .............. Line 153
 11. Create downloads directory ...................... Line 156
 12. Download videos using yt-dlp .................... Line 159
 13. Filter videos by duration (max 3 min) ........... Line 168
 14. Re-encode videos to uniform format .............. Line 192
     Store normalized videos in downloads/{YYYY_MM_DD}/normalized/
 15. Create file list for ffmpeg ..................... Line 222
 16. Create compilation directory .................... Line 228
 17. Compile videos using ffmpeg ..................... Line 231
 18. Generate bookmark report ........................ Line 245
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

    # Fetch URLs from Matrix room history
    matrix_urls = []
    if os.getenv('MATRIX_ACCESS_TOKEN'):
        from_token = None

        while True:
            params = {
                'access_token': os.getenv('MATRIX_ACCESS_TOKEN'),
                'dir': 'b',
                'limit': 100
            }
            if from_token:
                params['from'] = from_token

            matrix_resp = requests.get(
                f"{os.getenv('MATRIX_HOMESERVER')}/_matrix/client/v3/rooms/{os.getenv('MATRIX_ROOM_ID')}/messages",
                params=params
            ).json()

            for event in matrix_resp.get('chunk', []):
                ts = event.get('origin_server_ts', 0)
                if start_ts <= ts <= end_ts:
                    body = event.get('content', {}).get('body', '')
                    matrix_urls.extend(re.findall(r'https?://\S+', body))

            from_token = matrix_resp.get('end')
            if not from_token or (matrix_resp.get('chunk', [{}])[-1].get('origin_server_ts', 0) < start_ts):
                break

    # Deduplicate URLs from both sources
    urls = list(set(urls + matrix_urls))

    # Create downloads directory
    Path(f'downloads/{formatted_end_date}').mkdir(parents=True, exist_ok=True)
    Path(f'downloads/{formatted_end_date}/normalized').mkdir(parents=True, exist_ok=True)

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
    print(f"{idx} - {f}")
    normalized_path = Path(f'downloads/{formatted_end_date}/normalized/{f.name}')
    if not normalized_path.exists():
        result = subprocess.run([
            'ffmpeg',
            '-i', str(f),
            '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2',
            '-af', 'aresample=async=1:first_pts=0',
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-ar', '48000',
            '-ac', '2',
            '-b:a', '128k',
            '-preset', 'fast',
            '-crf', '23',
            '-r', '30',
            '-fps_mode', 'cfr',
            '-loglevel', 'error',
            '-y',
            str(normalized_path)
        ])
        if result.returncode != 0:
            print(f"Warning: Failed to normalize {f}")
    if normalized_path.exists():
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
    '-i', 'filelist.txt',
    '-c', 'copy',
    '-fflags', '+genpts',
    '-movflags', '+faststart',
    '-y',
    f'compilation/{formatted_end_date}.mp4'
])

# Generate bookmark report
template = Template(Path('templates/bookmark_report.md.j2').read_text())
report = template.render(
    start_date=args.start_date,
    end_date=args.end_date,
    bookmarks=filtered_bookmarks
)
Path(f'compilation/{formatted_end_date}.md').write_text(report)
