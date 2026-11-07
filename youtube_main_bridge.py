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
STATE = Path('link-runtime/state.json')
PLAN = Path('link-runtime/plan.json')


class YouTubeVideoHeld(RuntimeError):
    """A verified GET cannot confirm this saved ID; never authorizes insert."""


class YouTubeUploadHttpEvidence(RuntimeError):
    """Only bounded numeric HTTP evidence; never carries provider exception text."""

    def __init__(self, proof):
        super().__init__("sanitized_youtube_upload_failure")
        status = proof.get("http_status") if isinstance(proof, dict) else None
        self.http_status = status if type(status) is int and 400 <= status <= 599 else None
        self.stage = "videos.insert_resumable"


HELD_VERIFICATIONS = {'video_unavailable', 'upload_failed', 'upload_rejected', 'upload_deleted'}
UPLOAD_ERROR_CONTENT_LIMIT = 16_384
# Canonical labels only: youtube/v3/docs/errors, youtube/v3/docs/videos/insert
# and youtube/data/reference/rest/v3/core_errors on developers.google.com.
UPLOAD_ERROR_REASONS = frozenset({
    'authError', 'insufficientPermissions', 'forbidden',
    'quotaExceeded', 'dailyLimitExceeded', 'rateLimitExceeded',
    'userRateLimitExceeded', 'uploadLimitExceeded', 'backendError',
})


def sanitized_upload_error(exc):
    """Bounded provider evidence, not a diagnosis or permission to retry.

    Never stringify the exception or retain its message, headers, URL or body.
    Unknown/malformed reasons remain explicitly unknown, including alongside
    recognized reasons; only exact canonical allowlist values can leave here.
    """
    proof = {'reasons': [], 'unrecognized_reason': True}
    try:
        status = getattr(getattr(exc, 'resp', None), 'status', None)
        if type(status) is int and 400 <= status <= 599:
            proof['http_status'] = status
    except Exception:
        pass
    try:
        content = getattr(exc, 'content', None)
        if type(content) not in (bytes, str) or len(content) > UPLOAD_ERROR_CONTENT_LIMIT:
            return proof
        if isinstance(content, str):
            content = content.encode('utf-8')
        if len(content) > UPLOAD_ERROR_CONTENT_LIMIT:
            return proof
        payload = json.loads(content.decode('utf-8'))
        errors = payload.get('error', {}).get('errors')
        if not isinstance(errors, list) or not errors:
            return proof
        reasons = set()
        unknown = False
        for row in errors:
            reason = row.get('reason') if isinstance(row, dict) else None
            if type(reason) is str and reason in UPLOAD_ERROR_REASONS:
                reasons.add(reason)
            else:
                unknown = True
        proof.update(reasons=sorted(reasons), unrecognized_reason=unknown)
    except Exception:
        pass
    return proof


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def download(source, path):
    from public_link_runtime import download as source_download
    return source_download(source, path)


def verify_source_video(path):
    from public_link_runtime import verify_source_video as verify
    return verify(path)

ROUTES = {
    'tarladaki': ('channel1', 'TOKEN_CHANNEL1_JSON', 'UCrUF3mT4oF26JNBLcyKPcGQ'),
    'penguen': ('channel2', 'TOKEN_CHANNEL2_JSON', 'UCUG-NSyXpEt9PLt5RS4iumw'),
    'daily_laugh': ('daily_laugh', 'TOKEN_DAILY_LAUGH_LAB_JSON', 'UCF4KwI3alXzlExviMFmmJAA'),
    'gonle': ('gonle_dusen', 'TOKEN_GONLE_DUSEN_JSON', 'UCvSvo5WghuXqsjwLRmIz22g'),
}


from youtube_permission_circuit import (
    repeated_youtube_insert_forbidden, authorize_single_recheck,
)


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
    state['youtube_prepare_holds'] = []
    for key, item in selected(plans):
        if key in ledger:
            continue  # done, intent and uncertain are all protected from replay
        route = item['route']
        if repeated_youtube_insert_forbidden(ledger, route):
            # This route already has several separate real Google 403/forbidden
            # INSERT results. Avoid spending quota and creating fresh uncertain
            # rows until permission is repaired. Other platforms are untouched.
            release_id = os.getenv("YOUTUBE_FORBIDDEN_RELEASE_ID", "").strip()
            if not authorize_single_recheck(state, route, release_id):
                if route not in state['youtube_prepare_holds']:
                    state['youtube_prepare_holds'].append(route)
                continue
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


def verify_saved_upload(youtube, entry, expected):
    """GET-only reconciliation; ordinary processing is pending, never done."""
    payload = youtube.videos().list(part='snippet,status', id=entry['post_id']).execute(num_retries=2)
    rows = payload.get('items') if isinstance(payload, dict) else None
    entry['verification_status'] = 'video_identity_unverified'
    if rows == []:
        # A valid owner-authenticated empty result is an unavailable video,
        # not a new upload opportunity or proof of deletion. Keep the ID held
        # and visible in the independent audit instead of failing every tick.
        entry.update(status='held', verification_status='video_unavailable')
        raise YouTubeVideoHeld('YouTube video unavailable; original ID held, no retry')
    if (not isinstance(rows, list) or len(rows) != 1 or rows[0].get('id') != entry['post_id']
            or rows[0].get('snippet', {}).get('channelId') != expected):
        raise RuntimeError('YouTube upload identity not verified')
    status = rows[0].get('status', {})
    entry.update(status='accepted', privacy_status=status.get('privacyStatus'), upload_status=status.get('uploadStatus'))
    if entry['upload_status'] in {'failed', 'rejected', 'deleted'}:
        # Definitive provider result; preserve the accepted ID and never
        # upload this source again. The initial failed check remains visible.
        entry.update(status='held', verification_status='upload_' + entry['upload_status'])
        raise YouTubeVideoHeld('YouTube terminal upload state; ID preserved, no retry')
    if entry['privacy_status'] == 'public' and entry['upload_status'] == 'processed':
        entry.update(status='done', verification_status='public_processed_verified')
        return
    if entry['privacy_status'] == 'public' and entry['upload_status'] == 'uploaded':
        entry['verification_status'] = 'accepted_processing_pending'
        print(json.dumps({'platform': 'youtube', 'route': entry['route'],
                          'status': 'accepted_processing_pending', 'post_id': entry['post_id']}), flush=True)
        return
    entry['verification_status'] = 'processing_or_visibility_unverified'
    raise RuntimeError('YouTube processing or visibility not verified')


def current_local_preparation_failure(key, entry, state, run):
    """Positive current-plan proof only; never release or retry an upload.

    Meta preparation includes shared-source and cover checks. A failure does
    not prove the whole MP4 is corrupt, but a new fanout must preserve that
    local hold instead of uploading the same source to YouTube unchecked.
    """
    route, source, filename = entry.get('route'), entry.get('source_id'), entry.get('file')
    if (route not in ROUTES or not isinstance(source, str)
            or not re.fullmatch(r'[A-Za-z0-9_-]+', source)
            or entry.get('channel_id') != ROUTES[route][2]
            or key != f'{route}:{source}' or not isinstance(filename, str)
            or entry.get('run_id') != run or entry.get('status') != 'intent'
            or entry.get('post_id') is not None):
        return None
    rows = state.get('entries', {})
    if not isinstance(rows, dict):
        return None

    def locally_failed(platform):
        row = rows.get(f'{route}:{platform}:{source}')
        if not isinstance(row, dict):
            return False
        failure = row.get('failure')
        return (row.get('route') == route and row.get('platform') == platform
                and row.get('file') == filename and row.get('run_id') == run
                and row.get('status') == 'ready' and row.get('post_id') is None
                and isinstance(failure, dict)
                and failure.get('reason') == 'source_or_cover_preparation_failed'
                and failure.get('safe_to_repost') is True)

    # Existing accepted/legacy uploads do not need a current plan. Read it
    # only when exact new-intent local-failure evidence is present.
    if not any(locally_failed(p) for p in ('facebook', 'instagram')):
        return None
    try:
        plans = json.loads(PLAN.read_text())
        if not isinstance(plans, list):
            raise ValueError
        matching = [p for p in plans if isinstance(p, dict)
                    and p.get('route') == route and p.get('id') == source]
        if len(matching) != 1 or matching[0].get('name') != filename:
            raise ValueError
        item = matching[0]
        platforms = item.get('platforms')
        if (item.get('resume_container_id') or not isinstance(platforms, list)
                or not platforms or len(set(platforms)) != len(platforms)
                or any(p not in ('facebook', 'instagram') for p in platforms)):
            raise ValueError
    except (OSError, ValueError, TypeError):
        raise RuntimeError('YouTube local preparation plan unverified') from None
    if not all(locally_failed(p) for p in platforms):
        return None
    return {'run_id': run, 'route': route, 'source_id': source, 'file': filename,
            'platforms': sorted(platforms)}


def publish():
    if os.getenv('YOUTUBE_PUBLISHING_ENABLED') != 'true' or os.getenv('YOUTUBE_INTENT_ARCHIVED') != 'true':
        raise RuntimeError('YouTube publication requires enabled, archived intent')
    state = json.loads(STATE.read_text())
    ledger = state.get('youtube_entries', {})
    run = os.environ['GITHUB_RUN_ID']
    failed = bool(state.get('youtube_prepare_errors'))
    for key, entry in ledger.items():
        prior_hold = entry.get('verification_status') if entry.get('status') == 'held' else None
        reconciling = (bool(entry.get('post_id')) and (entry.get('status') == 'accepted'
                       or prior_hold in HELD_VERIFICATIONS))
        if not reconciling and (entry.get('status') != 'intent' or entry.get('run_id') != run
                or entry.get('attempt') != os.getenv('GITHUB_RUN_ATTEMPT', '1')):
            continue
        upload_in_progress = False
        try:
            if not reconciling:
                proof = current_local_preparation_failure(key, entry, state, run)
                if proof:
                    entry.update(status='held', verification_status='source_local_preparation_failed',
                                 external_post_attempted=False,
                                 source_local_preparation_proof=proof)
                    print(json.dumps({'platform': 'youtube', 'route': entry['route'],
                                      'status': 'held', 'verification_status': entry['verification_status'],
                                      'external_post_attempted': False}), flush=True)
                    continue
            target, secret, expected = ROUTES[entry['route']]
            identity = check_channel(target)
            if identity.get('status') != 'verified' or identity.get('channel_id') != expected or entry['channel_id'] != expected:
                raise RuntimeError('YouTube identity changed')
            credentials = Credentials.from_authorized_user_info(json.loads(os.environ[secret]))
            youtube = build('youtube', 'v3', credentials=credentials, cache_discovery=False)
            if reconciling:
                verify_saved_upload(youtube, entry, expected)
                continue
            # The permanent source marker detects accepted uploads before any replay.
            marker = '[avp-source:' + key + ']'
            existing = previous_upload(youtube, expected, marker, entry['title'])
            if existing:
                entry.update(status='accepted', post_id=existing, reconciled=True)
                save(STATE, state)
                verify_saved_upload(youtube, entry, expected)
                continue
            with tempfile.TemporaryDirectory() as temp:
                video = download(entry['source_id'], Path(temp) / 'source.mp4')
                verify_source_video(video)
                entry['status'] = 'uncertain'
                save(STATE, state)  # point of no blind retry before videos.insert
                upload_title = entry['title']
                upload_caption = entry['caption'] + '\n\n' + marker
                upload_in_progress = True
                post = upload_video(youtube, video, upload_title, upload_caption,
                                    privacy_status='public')
                upload_in_progress = False
                if not isinstance(post, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', post):
                    raise RuntimeError('YouTube returned no valid video ID')
                # Persist the accepted ID before any subsequent network read.
                entry.update(status='accepted', post_id=post)
                save(STATE, state)
                verify_saved_upload(youtube, entry, expected)
                if entry['status'] != 'done':
                    continue
                print(json.dumps({'platform': 'youtube', 'route': entry['route'], 'post_id': post,
                                  'privacy_status': entry['privacy_status']}), flush=True)
        except Exception as exc:
            upload_error = None
            if upload_in_progress and entry.get('status') == 'uncertain' and not entry.get('post_id'):
                upload_error = sanitized_upload_error(exc)
                entry['upload_error'] = upload_error
            unchanged_hold = (isinstance(exc, YouTubeVideoHeld)
                              and prior_hold == entry.get('verification_status'))
            if not unchanged_hold:
                failed = True
                # The previous generic RuntimeError discarded a real 403,
                # making API permission failures indistinguishable from media
                # errors in the persistent incident journal. Retain only the
                # sanitized HTTP status; never store Google's raw response.
                journal_error = (YouTubeUploadHttpEvidence(upload_error)
                                 if upload_error is not None else RuntimeError(type(exc).__name__))
                record_error('youtube_publish', 'youtube_publication_unverified',
                             route=entry.get('route'), platform='youtube',
                             error=journal_error, status=entry.get('status', ''))
            summary = {'platform': 'youtube', 'route': entry.get('route'),
                       'status': entry.get('status'), 'error_type': type(exc).__name__,
                       'verification_status': ('upload_unverified' if upload_error is not None else
                                               entry.get('verification_status', 'read_or_auth_failed'))}
            if upload_error is not None:
                summary['upload_error'] = upload_error
            print(json.dumps(summary), flush=True)
        finally:
            save(STATE, state)
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'publish'])
    (prepare if parser.parse_args().action == 'prepare' else publish)()
