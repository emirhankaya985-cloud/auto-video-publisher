"""YouTube fanout of current approved main plans, with archived upload intents."""
import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from youtube_uploader import upload_video
from publisher_error_journal import record_error
from youtube_readonly_connection import check_channel
from public_link_runtime import STATE, PLAN, save, download, verify_source_video

ROUTES = {
    'tarladaki': ('channel1', 'TOKEN_CHANNEL1_JSON', 'UCrUF3mT4oF26JNBLcyKPcGQ'),
    'penguen': ('channel2', 'TOKEN_CHANNEL2_JSON', 'UCUG-NSyXpEt9PLt5RS4iumw'),
    'daily_laugh': ('daily_laugh', 'TOKEN_DAILY_LAUGH_LAB_JSON', 'UCF4KwI3alXzlExviMFmmJAA'),
}


def selected(plans):
    seen = set()
    for item in plans:
        route, source = item.get('route'), item.get('id')
        if route not in ROUTES or item.get('resume_container_id'):
            continue
        if not isinstance(source, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', source):
            raise RuntimeError('Invalid YouTube source identity')
        key = route + ':' + source
        if key not in seen:
            seen.add(key)
            yield key, item


def prepare():
    state = json.loads(STATE.read_text())
    ledger = state.setdefault('youtube_entries', {})
    if not isinstance(ledger, dict):
        raise RuntimeError('Invalid YouTube ledger')
    plans = json.loads(PLAN.read_text())
    run = os.environ['GITHUB_RUN_ID']
    state['youtube_prepare_errors'] = []
    for key, item in selected(plans):
        if key in ledger:
            continue  # done, intent and uncertain are all protected from replay
        route = item['route']
        target, secret, expected = ROUTES[route]
        if not os.getenv(secret, '').strip():
            state['youtube_prepare_errors'].append(route + ': missing_secret')
            record_error('youtube_prepare', 'missing_secret', route=route, platform='youtube')
            continue
        identity = check_channel(target)
        if identity.get('status') != 'verified' or identity.get('channel_id') != expected:
            raise RuntimeError('YouTube channel identity not verified: ' + route)
        caption = item.get('captions', {}).get('facebook') or item.get('captions', {}).get('instagram')
        if not isinstance(caption, str) or not caption.strip():
            raise RuntimeError('YouTube caption missing')
        ledger[key] = {'status': 'intent', 'run_id': run, 'attempt': os.getenv('GITHUB_RUN_ATTEMPT', '1'), 'route': route,
                       'source_id': item['id'], 'file': item['name'], 'channel_id': expected,
                       'caption': caption, 'title': Path(item['name']).stem.replace('_', ' ')[:100],
                       'caption_hash': hashlib.sha256(caption.encode()).hexdigest()}
    save(STATE, state)


def previous_upload(youtube, expected, marker, title):
    channel = youtube.channels().list(part='contentDetails', mine=True).execute()['items']
    if len(channel) != 1 or channel[0]['id'] != expected:
        raise RuntimeError('YouTube channel changed')
    playlist = channel[0]['contentDetails']['relatedPlaylists']['uploads']
    token = None
    seen = set()
    for _ in range(100):
        args = dict(part='snippet', playlistId=playlist, maxResults=50)
        if token:
            args['pageToken'] = token
        page = youtube.playlistItems().list(**args).execute()
        for row in page.get('items', []):
            snippet = row['snippet']
            if marker in snippet.get('description', ''):
                return snippet['resourceId']['videoId']
            if snippet.get('title', '').strip().casefold() == title.strip().casefold():
                raise RuntimeError('Existing YouTube title requires reconciliation')
        token = page.get('nextPageToken')
        if not token:
            return None
        if token in seen:
            break
        seen.add(token)
    raise RuntimeError('YouTube history incomplete')


def publish():
    if os.getenv('YOUTUBE_PUBLISHING_ENABLED') != 'true' or os.getenv('YOUTUBE_INTENT_ARCHIVED') != 'true':
        raise RuntimeError('YouTube publication requires enabled, archived intent')
    state = json.loads(STATE.read_text())
    ledger = state.get('youtube_entries', {})
    run = os.environ['GITHUB_RUN_ID']
    failed = bool(state.get('youtube_prepare_errors'))
    for key, entry in ledger.items():
        reconciling = entry.get('status') == 'accepted' and bool(entry.get('post_id'))
        if not reconciling and (entry.get('status') != 'intent' or entry.get('run_id') != run
                or entry.get('attempt') != os.getenv('GITHUB_RUN_ATTEMPT', '1')):
            continue
        try:
            target, secret, expected = ROUTES[entry['route']]
            identity = check_channel(target)
            if identity.get('status') != 'verified' or identity.get('channel_id') != expected or entry['channel_id'] != expected:
                raise RuntimeError('YouTube identity changed')
            credentials = Credentials.from_authorized_user_info(json.loads(os.environ[secret]))
            youtube = build('youtube', 'v3', credentials=credentials, cache_discovery=False)
            if reconciling:
                rows = youtube.videos().list(part='snippet,status', id=entry['post_id']).execute().get('items', [])
                if (len(rows) == 1 and rows[0]['snippet'].get('channelId') == expected
                        and rows[0]['status'].get('privacyStatus') == 'public'
                        and rows[0]['status'].get('uploadStatus') == 'processed'):
                    entry.update(status='done', privacy_status='public', upload_status='processed')
                else:
                    raise RuntimeError('YouTube processing or public status pending')
                continue
            # The permanent source marker detects accepted uploads before any replay.
            marker = '[avp-source:' + key + ']'
            existing = previous_upload(youtube, expected, marker, entry['title'])
            if existing:
                entry.update(status='accepted', post_id=existing, reconciled=True)
                raise RuntimeError('YouTube existing source requires status verification')
            with tempfile.TemporaryDirectory() as temp:
                video = download(entry['source_id'], Path(temp) / 'source.mp4')
                verify_source_video(video)
                entry['status'] = 'uncertain'
                save(STATE, state)  # point of no blind retry before videos.insert
                post = upload_video(youtube, video, entry['title'], entry['caption'] + '\n\n' + marker,
                                    privacy_status='public')
                if not isinstance(post, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', post):
                    raise RuntimeError('YouTube returned no valid video ID')
                proof = youtube.videos().list(part='snippet,status', id=post).execute()
                rows = proof.get('items', [])
                if len(rows) != 1 or rows[0]['snippet'].get('channelId') != expected:
                    raise RuntimeError('YouTube upload verification failed')
                entry.update(status='accepted', post_id=post, privacy_status=rows[0]['status'].get('privacyStatus'),
                             upload_status=rows[0]['status'].get('uploadStatus'))
                if entry['privacy_status'] != 'public' or entry['upload_status'] != 'processed':
                    raise RuntimeError('YouTube public publication not confirmed')
                entry['status'] = 'done'
                print(json.dumps({'platform': 'youtube', 'route': entry['route'], 'post_id': post,
                                  'privacy_status': entry['privacy_status']}), flush=True)
        except Exception as exc:
            failed = True
            record_error('youtube_publish', 'youtube_publication_unverified',
                         route=entry.get('route'), platform='youtube',
                         error=RuntimeError(type(exc).__name__))
            print(json.dumps({'platform': 'youtube', 'route': entry.get('route'),
                              'status': entry.get('status'), 'error_type': type(exc).__name__}), flush=True)
        finally:
            save(STATE, state)
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'publish'])
    (prepare if parser.parse_args().action == 'prepare' else publish)()
