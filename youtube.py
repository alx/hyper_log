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
  1. Load cached credentials ......................... Line 44
  2. Authenticate with YouTube API ................... Line 50
  3. Find latest compilation video ................... Line 79
  4. Read description from markdown .................. Line 82
  5. Upload video to YouTube ......................... Line 86
"""

import os
import pickle
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Load cached credentials
token_file = Path('.youtube_token.pickle')
creds = None
if token_file.exists():
    with open(token_file, 'rb') as token:
        creds = pickle.load(token)

# Authenticate with YouTube API
if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        credentials_data = {
            'installed': {
                'client_id': os.getenv('YOUTUBE_CLIENT_ID'),
                'client_secret': os.getenv('YOUTUBE_CLIENT_SECRET'),
                'project_id': os.getenv('YOUTUBE_PROJECT_ID'),
                'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                'token_uri': 'https://oauth2.googleapis.com/token',
                'redirect_uris': ['http://localhost']
            }
        }
        credentials_file = Path('.youtube_credentials_temp.json')
        credentials_file.write_text(__import__('json').dumps(credentials_data))
        flow = InstalledAppFlow.from_client_secrets_file(
            str(credentials_file),
            ['https://www.googleapis.com/auth/youtube.upload']
        )
        creds = flow.run_local_server(port=0)
        credentials_file.unlink()
    with open(token_file, 'wb') as token:
        pickle.dump(creds, token)

# Build YouTube service
youtube = build('youtube', 'v3', credentials=creds)

# Find latest compilation video
video_file = max(Path('compilation').glob('*.mp4'), key=lambda f: f.stat().st_mtime)

# Read description from markdown
description_file = Path(str(video_file).replace('.mp4', '.md'))
description = description_file.read_text()

# Upload video to YouTube
request_body = {
    'snippet': {
        'title': f'Video Compilation - {video_file.stem}',
        'description': description,
        'categoryId': '22'
    },
    'status': {
        'privacyStatus': 'private'
    }
}
media = MediaFileUpload(str(video_file), resumable=True)
response = youtube.videos().insert(
    part='snippet,status',
    body=request_body,
    media_body=media
).execute()

print(f"✅ Uploaded: https://www.youtube.com/watch?v={response['id']}")