"""Owner-authorized first-season Instagram campaign and subsequent Facebook audit."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import tempfile

import requests
import publisher_alert_history as archive
from threads_toonzone_season import ordered_catalog, caption
from publisher_recovery import read_with_retry, classify_meta_failure
from threads_live_publish import error_label

WORKFLOW = '.github/workflows/toonzone_instagram_season.yml'
ROOT = Path('toonzone-instagram-season-runtime')
HISTORY = ROOT / 'alert-history.json'
PLAN = ROOT / 'plan.json'
NAMES = ('toonzone-instagram-season-intent', 'toonzone-instagram-season-result')
CAMPAIGN = 'toonzone-instagram-season-one-2026-11-05'
AUDITED_PREWRITE_RUN = '42011620370'


def page_for_toonzone():
    from meta_auth_loader import load_meta_auth
    pages = [page for page in load_meta_auth()['pages']
             if page['page_name'] == 'ToonZone' and str(page['page_id']) == '1298191963387372']
    if len(pages) != 1:
        raise RuntimeError('toonzone_meta_identity_missing')
    return pages[0]


def graph_get(page, identifier, fields):
    from cloud_omnichannel_publisher import GRAPH_API_VERSION
    response = read_with_retry(requests.get,
        f'https://graph.facebook.com/{GRAPH_API_VERSION}/{identifier}',
        headers={'Authorization': 'Bearer ' + page['page_token']},
        params={'fields': fields}, timeout=25, allow_redirects=False, graph_read=True)
    if response.status_code != 200:
        raise RuntimeError(f'meta_read_http_{response.status_code}')
    data = response.json()
    if not isinstance(data, dict) or data.get('error') or str(data.get('id')) != str(identifier):
        raise RuntimeError('meta_read_identity_mismatch')
    return data


def instagram_identity(page):
    if not str(page.get('instagram_id', '')).isdecimal():
        raise RuntimeError('toonzone_instagram_not_linked')
    data = graph_get(page, page['instagram_id'], 'id,username')
    if not data.get('username'):
        raise RuntimeError('toonzone_instagram_username_missing')
    return str(data['id'])


def prepare(run_id):
    from public_link_runtime import FOLDERS, inventory, graph_rows
    page = page_for_toonzone()
    user_id = instagram_identity(page)
    # Complete history must be readable before reserving any new publications.
    existing = graph_rows(page, 'instagram')
    history = archive.restore(names=NAMES, workflow_path=WORKFLOW)
    catalog = ordered_catalog(inventory(FOLDERS['toonzone']))
    plans = []
    now = archive.now_utc().isoformat()
    for item in catalog:
        key = archive.identity(CAMPAIGN, 'toonzone', 'instagram', item['id'])
        prior = history['records'].get(key)
        recovered = False
        if (prior and prior.get('intent_run_id') == AUDITED_PREWRITE_RUN
                and prior.get('status') == 'reserved' and prior.get('user_id') == user_id
                and prior.get('source_id') == item['id'] and prior.get('file') == item['name']):
            # This exact run stopped at the first local cover-name check.
            # No upload or media_publish call was reached for any of its 48 parts.
            recovered = True
            prior = None
        if prior:
            if (prior.get('status') != 'verified' or prior.get('user_id') != user_id
                    or prior.get('file') != item['name'] or not prior.get('post_id')):
                raise RuntimeError('instagram_season_previous_intent_unresolved')
            continue
        text, marker = caption(item['episode'], item['part'])
        history['records'][key] = dict(route='toonzone', platform='instagram',
            source_id=item['id'], file=item['name'], user_id=user_id,
            marker=marker, caption=text, status='reserved', last_seen=now, intent_run_id=run_id)
        if recovered:
            history['records'][key]['audited_prewrite_run'] = AUDITED_PREWRITE_RUN
        plans.append(dict(key=key, text=text, **item))
    archive.save(HISTORY, archive.validate(history))
    archive.save(PLAN, dict(run_id=run_id, plans=plans, user_id=user_id,
                           existing_video_count=len(existing)))
    print(f'INSTAGRAM_SEASON_RESERVED {len(plans)}', flush=True)


def execute(run_id):
    from public_link_runtime import download_verified_publication_video, generate_part_cover
    from cloud_omnichannel_publisher import create_instagram_cover_video, upload_instagram_reel
    from instagram_media_compat import prepare_instagram_upload
    if os.getenv('INSTAGRAM_SEASON_INTENT_ARCHIVED') != 'true':
        raise RuntimeError('instagram_season_intent_not_archived')
    data, history = archive.read(PLAN), archive.validate(archive.read(HISTORY))
    page = page_for_toonzone()
    user_id = instagram_identity(page)
    if data['run_id'] != run_id or data['user_id'] != user_id:
        raise RuntimeError('instagram_season_run_or_identity_mismatch')
    for item in data['plans']:
        record = history['records'][item['key']]
        if (record['status'] != 'reserved' or record['intent_run_id'] != run_id
                or record['user_id'] != user_id or record['source_id'] != item['id']
                or record['file'] != item['name'] or record['caption'] != item['text']):
            raise RuntimeError('instagram_season_reservation_mismatch')
        try:
            with tempfile.TemporaryDirectory(prefix='toonzone-instagram-season-') as directory:
                temp = Path(directory)
                source = download_verified_publication_video(item['id'], temp / 'source.mp4')
                with source.open('rb') as handle:
                    record['source_sha256'] = hashlib.file_digest(handle, 'sha256').hexdigest()
                cover = generate_part_cover(source, item['name'], temp / (Path(item['name']).stem + '.png'))
                covered = create_instagram_cover_video(source, cover, temp / 'covered.mp4')
                video = prepare_instagram_upload(covered, temp / 'instagram.mp4', toonzone_compact=True)
                record['status'] = 'attempted'
                archive.save(HISTORY, history)
                post_id = str(upload_instagram_reel(page, str(video), item['text'], append_store_link=False))
                if not post_id.isdecimal():
                    raise RuntimeError('instagram_season_post_id_missing')
                record['post_id'] = post_id
                archive.save(HISTORY, history)
                evidence = graph_get(page, post_id, 'id,caption,media_type,permalink')
                if (evidence.get('media_type') != 'VIDEO' or evidence.get('caption') != item['text']
                        or not str(evidence.get('permalink', '')).startswith('https://www.instagram.com/')):
                    raise RuntimeError('instagram_season_post_unverified')
                record.update(status='verified', permalink=evidence['permalink'])
                archive.save(HISTORY, history)
                print(f"INSTAGRAM_SEASON_VERIFIED {item['name']} {post_id} {record['permalink']}", flush=True)
        except Exception as exc:
            record['failure'] = error_label(exc)
            record['diagnostic'] = classify_meta_failure(exc)
            archive.save(HISTORY, history)
            print(f"INSTAGRAM_SEASON_STOPPED {item['name']} {record['failure']}", flush=True)
            raise RuntimeError('instagram_season_stopped_before_next_part') from None
    print('INSTAGRAM_SEASON_COMPLETE', flush=True)


def audit_facebook():
    from public_link_runtime import graph_rows
    page = page_for_toonzone()
    identity = graph_get(page, page['page_id'], 'id,name,is_published')
    videos = graph_rows(page, 'facebook')
    matches = {}
    for row in videos:
        text = str(row.get('description') or '')
        episode = re.search(r'\bS01E(\d{2})\b', text)
        part = re.search(r'(?:Part\s*|#Part)([1-4])\b', text, re.I)
        if episode and part and 1 <= int(episode[1]) <= 12:
            slot = f'S01E{int(episode[1]):02d} Part{part[1]}'
            matches.setdefault(slot, []).append(str(row['id']))
    expected = [f'S01E{episode:02d} Part{part}' for episode in range(1, 13) for part in range(1, 5)]
    report = dict(page_id=identity['id'], page_name=identity['name'],
                  is_published=identity.get('is_published'), visible_videos=len(videos),
                  first_season_caption_matches=matches,
                  missing_caption_slots=[slot for slot in expected if slot not in matches],
                  measured_at=archive.now_utc().isoformat(),
                  scope='Read-only visible-video and caption audit. Account copyright status unavailable.')
    archive.save(ROOT / 'facebook-audit.json', report)
    print(f"FACEBOOK_AUDIT videos={len(videos)} season_slots={len(matches)}/48 is_published={report['is_published']}", flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'publish', 'facebook'])
    mode = parser.parse_args().mode
    if mode == 'facebook':
        audit_facebook()
    elif mode == 'prepare':
        prepare(os.environ['GITHUB_RUN_ID'])
    else:
        execute(os.environ['GITHUB_RUN_ID'])
