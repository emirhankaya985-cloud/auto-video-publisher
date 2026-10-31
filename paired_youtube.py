"""Pair YouTube with selected Meta sources; never select an independent queue."""
import hashlib
import json
import os
from pathlib import Path
from publisher_error_journal import record_error

CHANNELS = {
    'tarladaki': ('TOKEN_CHANNEL1_JSON', 'UCrUF3mT4oF26JNBLcyKPcGQ'),
    'penguen': ('TOKEN_CHANNEL2_JSON', 'UCUG-NSyXpEt9PLt5RS4iumw'),
    'daily_laugh': ('TOKEN_DAILY_LAUGH_LAB_JSON', 'UCF4KwI3alXzlExviMFmmJAA'),
    'gonle': ('TOKEN_GONLE_DUSEN_JSON', 'UCvSvo5WghuXqsjwLRmIz22g'),
}
SCOPES = ['https://www.googleapis.com/auth/youtube.upload',
          'https://www.googleapis.com/auth/youtube.readonly']


def enabled():
    return os.getenv('YOUTUBE_PUBLISHING_ENABLED', 'false').lower() == 'true'


def client_for(route):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    secret, expected = CHANNELS[route]
    raw = os.getenv(secret, '')
    if not raw:
        raise RuntimeError('YouTube credential missing')
    data = json.loads(raw)
    if not set(SCOPES).issubset(set(data.get('scopes', []))):
        raise RuntimeError('YouTube credential scopes incomplete')
    credentials = Credentials.from_authorized_user_info(data, SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    client = build('youtube', 'v3', credentials=credentials, cache_discovery=False)
    items = client.channels().list(part='id', mine=True).execute().get('items', [])
    if len(items) != 1 or items[0].get('id') != expected:
        raise RuntimeError('YouTube channel identity mismatch')
    return client


def plan_paired_youtube(plans, state, *, audit=False):
    if not enabled() or audit:
        return plans
    if os.getenv('IG_AUDITED_RESCUE_ONLY', 'false').lower() == 'true':
        return plans
    entries = state.setdefault('entries', {})
    checked = {}
    for item in plans:
        route = item.get('route')
        if route not in CHANNELS or item.get('resume_container_id'):
            continue
        key = f"{route}:youtube:{item['id']}"
        # Never turn an old/ambiguous upload into a fresh upload. A pending
        # upload holds the whole channel until its outcome is reconciled.
        if entries.get(key, {}).get('status') in {'done', 'intent', 'uncertain'}:
            continue
        if any(e.get('route') == route and e.get('platform') == 'youtube'
               and e.get('status') in {'intent', 'uncertain'}
               and e.get('run_id') != os.getenv('GITHUB_RUN_ID') for e in entries.values()):
            continue
        if route not in checked:
            try:
                client_for(route)
                checked[route] = True
            except Exception:
                checked[route] = False
                record_error('youtube_preflight', 'youtube_connection_unavailable', route=route, platform='youtube')
                # Fixed text only: API exception bodies can contain credentials.
                print(f'YouTube held: {route}: credential or channel check failed', flush=True)
        if not checked[route]:
            continue
        captions = item.setdefault('captions', {})
        caption = captions.get('youtube') or captions.get('facebook') or captions.get('instagram') or Path(item['name']).stem
        title = Path(item['name']).stem[:100]
        captions['youtube'] = caption[:5000]
        item['youtube_title'] = title
        if 'youtube' not in item['platforms']:
            item['platforms'].append('youtube')
        parent = next((entries.get(f"{route}:{p}:{item['id']}", {})
                       for p in item['platforms'] if p != 'youtube'), {})
        entries[key] = {
            'route': route, 'platform': 'youtube', 'status': 'intent',
            'file': item['name'], 'source_id': item['id'],
            'caption_hash': hashlib.sha256(captions['youtube'].encode()).hexdigest(),
            'publish_caption': captions['youtube'],
            'youtube_title': title, 'channel_id': CHANNELS[route][1],
            'day': parent.get('day'), 'run_id': os.getenv('GITHUB_RUN_ID'),
        }
    return plans


def publish_paired_youtube(item, video, state):
    if not enabled() or item['route'] not in CHANNELS:
        raise RuntimeError('YouTube publishing disabled for this route')
    entry = state['entries'][f"{item['route']}:youtube:{item['id']}"]
    if (entry.get('status') != 'uncertain'
            or entry.get('run_id') != os.getenv('GITHUB_RUN_ID')
            or entry.get('source_id') != item['id']
            or entry.get('youtube_title') != item.get('youtube_title')
            or entry.get('publish_caption') != item['captions']['youtube']
            or entry.get('channel_id') != CHANNELS[item['route']][1]):
        raise RuntimeError('YouTube persisted upload intent mismatch')
    client = client_for(item['route'])
    from googleapiclient.http import MediaFileUpload
    language = 'en' if item['route'] == 'daily_laugh' else 'tr'
    body = {'snippet': {'title': item['youtube_title'],
                        'description': item['captions']['youtube'],
                        'categoryId': '22', 'defaultLanguage': language},
            'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}}
    request = client.videos().insert(part='snippet,status', body=body,
        media_body=MediaFileUpload(str(video), chunksize=4*1024*1024, resumable=True))
    result = None
    while result is None:
        _, result = request.next_chunk(num_retries=0)
    video_id = result.get('id')
    if not isinstance(video_id, str) or not video_id:
        raise RuntimeError('YouTube upload result unconfirmed')
    return {'id': video_id, 'url': f'https://www.youtube.com/watch?v={video_id}'}
