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
import json
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
    Path('compilation').mkdir(exist_ok=True)
    Path(f'compilation/{formatted_end_date}_karakeep.json').write_text(json.dumps(response, indent=2))

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

    # Save Matrix URLs
    Path(f'compilation/{formatted_end_date}_matrix.json').write_text(json.dumps(matrix_urls, indent=2))

    # Deduplicate URLs from both sources
    urls = list(set(urls + matrix_urls))

    # Create downloads directory
    Path(f'downloads/{formatted_end_date}').mkdir(parents=True, exist_ok=True)
    Path(f'downloads/{formatted_end_date}/normalized').mkdir(parents=True, exist_ok=True)

    # Dictionary to store video metadata: video_id -> {title, url, duration}
    video_metadata = {}

    # Download videos using yt-dlp
    for url in urls:
        # Extract metadata to check duration before downloading
        result = subprocess.run([
            'yt-dlp',
            '-j',
            '--cookies-from-browser', 'firefox',
            url
        ], capture_output=True, text=True)

        try:
            metadata = json.loads(result.stdout)
            duration = metadata.get('duration')

            if duration is None:
                print(f"Warning: Could not extract duration for {url}, skipping")
                continue

            if duration > 180:
                print(f"Skipping {url}: duration {duration}s exceeds 180s limit")
                continue

            # Store video metadata
            video_id = metadata.get('id', url.split('/')[-1])
            video_metadata[video_id] = {
                'title': metadata.get('title', 'Untitled'),
                'url': metadata.get('webpage_url', url),
                'duration': duration,
                'uploader': metadata.get('uploader', 'Unknown')
            }

            print(f"Downloading {url} (duration: {duration}s)")
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Warning: Failed to parse metadata for {url}: {e}, skipping")
            continue

        # Download the video
        subprocess.run([
            'yt-dlp',
            '--cookies-from-browser', 'firefox',
            '-o', f'downloads/{formatted_end_date}/%(id)s.%(ext)s',
            url
        ])

    # Save video metadata to JSON file
    Path('compilation').mkdir(exist_ok=True)
    Path(f'compilation/{formatted_end_date}_metadata.json').write_text(
        json.dumps(video_metadata, indent=2)
    )

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
    # Load existing metadata from JSON file
    metadata_file = Path(f'compilation/{formatted_end_date}_metadata.json')
    if metadata_file.exists():
        video_metadata = json.loads(metadata_file.read_text())
    else:
        print("Warning: No metadata file found, using filenames as titles")
        video_metadata = {}  # Initialize empty metadata dict for merge-only mode

# Re-encode all videos to uniform format (H.264/AAC/MP4) with consistent dimensions
normalized_files = []
for idx, f in enumerate(files):
    # Skip directories
    if not f.is_file():
        continue

    print(f"{idx} - {f}")

    # Always output as .mp4 for H.264/AAC compatibility
    normalized_path = Path(f'downloads/{formatted_end_date}/normalized/{f.stem}.mp4')

    # Check if normalized file exists and is valid (> 1KB)
    needs_normalization = True
    if normalized_path.exists():
        if normalized_path.stat().st_size > 1024:
            needs_normalization = False
        else:
            print(f"Warning: Found corrupted normalized file {normalized_path.name}, re-normalizing...")
            normalized_path.unlink()

    if needs_normalization:
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

    # Only add files that exist and are valid (> 1KB)
    if normalized_path.exists() and normalized_path.stat().st_size > 1024:
        normalized_files.append(normalized_path)

# Calculate timestamps for each video in the compilation
compilation_videos = []
cumulative_timestamp = 0.0

for video_file in normalized_files:
    # Get duration of normalized video
    result = subprocess.run([
        'ffprobe',
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        str(video_file)
    ], capture_output=True, text=True)

    try:
        duration = float(result.stdout.strip())
    except (ValueError, AttributeError):
        duration = 0.0

    # Extract video_id from filename (stem without extension)
    video_id = video_file.stem

    # Get metadata if available, otherwise use filename
    metadata = video_metadata.get(video_id, {
        'title': video_id,
        'url': f'https://unknown/{video_id}',
        'uploader': 'Unknown'
    })

    # Format timestamp as HH:MM:SS
    hours = int(cumulative_timestamp // 3600)
    minutes = int((cumulative_timestamp % 3600) // 60)
    seconds = int(cumulative_timestamp % 60)
    timestamp_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    # Format duration as MM:SS
    dur_minutes = int(duration // 60)
    dur_seconds = int(duration % 60)
    duration_str = f"{dur_minutes:02d}:{dur_seconds:02d}"

    compilation_videos.append({
        'index': len(compilation_videos) + 1,
        'title': metadata['title'],
        'url': metadata['url'],
        'uploader': metadata.get('uploader', 'Unknown'),
        'timestamp': timestamp_str,
        'timestamp_seconds': int(cumulative_timestamp),
        'duration': duration_str,
        'duration_seconds': duration,
        'video_id': video_id
    })

    cumulative_timestamp += duration

# Calculate total compilation duration
total_hours = int(cumulative_timestamp // 3600)
total_minutes = int((cumulative_timestamp % 3600) // 60)
total_seconds = int(cumulative_timestamp % 60)
total_duration_str = f"{total_hours:02d}:{total_minutes:02d}:{total_seconds:02d}"

# Create file list for ffmpeg using normalized files
Path(f'compilation/{formatted_end_date}_filelist.txt').write_text('\n'.join(
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
    '-i', f'compilation/{formatted_end_date}_filelist.txt',
    '-c', 'copy',
    '-fflags', '+genpts',
    '-movflags', '+faststart',
    '-y',
    f'compilation/{formatted_end_date}.mp4'
])

# Generate compilation report
template = Template(Path('templates/bookmark_report.md.j2').read_text())
report = template.render(
    start_date=args.start_date,
    end_date=args.end_date,
    videos=compilation_videos,
    total_duration=total_duration_str,
    total_videos=len(compilation_videos),
    compilation_file=f'{formatted_end_date}.mp4'
)
Path(f'compilation/{formatted_end_date}.md').write_text(report)
