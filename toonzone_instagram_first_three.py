"""Publish only the explicitly requested first three episodes with exact Drive covers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

import requests
import publisher_alert_history as archive
from threads_toonzone_season import ordered_catalog
from toonzone_instagram_season import page_for_toonzone, instagram_identity, graph_get

WORKFLOW = '.github/workflows/toonzone_instagram_first_three.yml'
NAMES = ('toonzone-first-three-intent', 'toonzone-first-three-result')
ROOT = Path('toonzone-first-three-runtime')
HISTORY = ROOT / 'alert-history.json'
PLAN = ROOT / 'plan.json'
CAMPAIGN = 'toonzone-instagram-first-three-real-covers-2026-11-05'
EXPECTED_INSTAGRAM_ID = '17841477404255851'


def text_for(item):
    from toonzone_episode_summaries import episode_summary
    from ordered_channels import toonzone_metadata
    episode, part = item['episode'], item['part']
    title = toonzone_metadata(Path(item['name']).stem)['title'].split(' — Part ', 1)[0]
    return (f'🎬 Sürekli Dizi — {title}\n📺 Sezon 1 • Bölüm {episode} • Part {part}/4\n\n'
            f'📖 {episode_summary(1, episode)}\n\n'
            '#SürekliDizi #RegularShow #ToonZone #Mordecai #Rigby #ÇizgiFilm '
            '#Animasyon #TürkçeDublaj #Komedi #ÇizgiFilmSahneleri #Benson #Skips #Pops '
            f'#Sezon1 #Bölüm{episode} #S01E{episode:02d} #Part{part}')


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def cover_distance(reference, actual, *, reference_is_frame=False):
    from PIL import Image, ImageOps, ImageChops, ImageStat
    with Image.open(reference) as source, Image.open(actual) as observed:
        source = source.convert('RGB')
        observed = observed.convert('RGB')
        if reference_is_frame:
            expected = ImageOps.fit(source, observed.size)
        else:
            expected = ImageOps.pad(source, observed.size, color=(0, 0, 0))
        difference = ImageChops.difference(expected.resize((90, 160)), observed.resize((90, 160)))
        return sum(ImageStat.Stat(difference).rms) / (3 * 255)


def prepare(run_id):
    from public_link_runtime import FOLDERS, inventory, graph_rows, download, probe
    page = page_for_toonzone()
    user_id = instagram_identity(page)
    if user_id != EXPECTED_INSTAGRAM_ID:
        raise RuntimeError("toonzone_instagram_identity_changed")
    live = {str(row['id']): row for row in graph_rows(page, 'instagram')}
    history = archive.restore(names=NAMES, workflow_path=WORKFLOW)
    videos = [item for item in ordered_catalog(inventory(FOLDERS['toonzone'])) if item['episode'] <= 3]
    if [(item['episode'], item['part']) for item in videos] != [(e, p) for e in range(1, 4) for p in range(1, 5)]:
        raise RuntimeError('first_three_episode_order_invalid')
    covers = inventory(FOLDERS['covers'])
    plans = []
    (ROOT / 'covers').mkdir(parents=True, exist_ok=True)
    for item in videos:
        key = archive.identity(CAMPAIGN, 'toonzone', 'instagram', item['id'])
        prior = history['records'].get(key)
        if prior:
            if (prior.get('status') != 'verified' or prior.get('user_id') != user_id
                    or prior.get('file') != item['name'] or str(prior.get('post_id')) not in live):
                raise RuntimeError('first_three_previous_intent_unresolved')
            continue
        cover_name = Path(item['name']).stem + '.png'
        cover = covers.get(cover_name)
        if not cover:
            raise RuntimeError('exact_drive_cover_missing')
        path = download(cover['id'], ROOT / 'covers' / cover_name)
        streams = probe(path).get('streams', [])
        if not any(stream.get('codec_type') == 'video' and stream.get('width', 0) > 0 for stream in streams):
            raise RuntimeError('exact_drive_cover_unreadable')
        text = text_for(item)
        record = dict(route='toonzone', platform='instagram', user_id=user_id,
                      source_id=item['id'], file=item['name'], cover_id=cover['id'],
                      cover_file=cover_name, cover_sha256=digest(path), caption=text,
                      status='reserved', intent_run_id=run_id, last_seen=archive.now_utc().isoformat())
        history['records'][key] = record
        plans.append(dict(item, key=key, cover_path=str(path), text=text))
    archive.save(HISTORY, archive.validate(history))
    archive.save(PLAN, dict(run_id=run_id, user_id=user_id, plans=plans))
    print(f'FIRST_THREE_RESERVED parts={len(plans)} exact_covers={len(plans)}', flush=True)


def thumbnail(page, post_id, destination):
    evidence = None
    for attempt in range(5):
        evidence = graph_get(page, post_id, 'id,caption,media_type,permalink,thumbnail_url')
        if evidence.get('thumbnail_url'):
            break
        time.sleep(2)
    url = str(evidence.get('thumbnail_url') or '')
    parsed = urlsplit(url)
    host = parsed.hostname or ''
    if parsed.scheme != 'https' or not host.endswith(('.cdninstagram.com', '.fbcdn.net')):
        raise RuntimeError('instagram_thumbnail_host_unverified')
    with requests.get(url, stream=True, timeout=30, allow_redirects=False) as response:
        if response.status_code != 200:
            raise RuntimeError('instagram_thumbnail_unavailable')
        size = 0
        with destination.open('wb') as output:
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 10_000_000:
                    raise RuntimeError('instagram_thumbnail_too_large')
                output.write(chunk)
    return evidence


def execute(run_id):
    from public_link_runtime import download_verified_publication_video
    from cloud_omnichannel_publisher import create_instagram_cover_video, upload_instagram_reel
    from instagram_media_compat import prepare_instagram_upload
    from publisher_recovery import classify_meta_failure
    from telegram_notifications import send_telegram
    if os.getenv('FIRST_THREE_INTENT_ARCHIVED') != 'true':
        raise RuntimeError('first_three_intent_not_archived')
    data, history = archive.read(PLAN), archive.validate(archive.read(HISTORY))
    page = page_for_toonzone()
    user_id = instagram_identity(page)
    if user_id != EXPECTED_INSTAGRAM_ID:
        raise RuntimeError("toonzone_instagram_identity_changed")
    if data['run_id'] != run_id or data['user_id'] != user_id:
        raise RuntimeError('first_three_identity_changed')
    previews = ROOT / 'previews'
    previews.mkdir(parents=True, exist_ok=True)
    for item in data['plans']:
        record = history['records'][item['key']]
        if (record['status'] != 'reserved' or record['intent_run_id'] != run_id
                or record['source_id'] != item['id'] or record['caption'] != item['text']
                or record['user_id'] != user_id or digest(item['cover_path']) != record['cover_sha256']):
            raise RuntimeError('first_three_reservation_changed')
        try:
            with tempfile.TemporaryDirectory(prefix='toonzone-exact-cover-') as directory:
                temp = Path(directory)
                source = download_verified_publication_video(item['id'], temp / 'source.mp4')
                record['source_sha256'] = digest(source)
                covered = create_instagram_cover_video(source, Path(item['cover_path']), temp / 'covered.mp4', preserve_full_cover=True)
                video = prepare_instagram_upload(covered, temp / 'instagram.mp4', force_transcode=True, recovery_v3=True)
                frame = previews / (Path(item['name']).stem + '-prepared.jpg')
                subprocess.run(['ffmpeg', '-y', '-i', str(video), '-frames:v', '1', str(frame)],
                               check=True, capture_output=True, timeout=60)
                record['prepared_cover_distance'] = cover_distance(item['cover_path'], frame)
                if record['prepared_cover_distance'] > 0.12:
                    raise RuntimeError('prepared_first_frame_does_not_match_drive_cover')
                record['upload_sha256'] = digest(video)
                record['status'] = 'attempted'
                archive.save(HISTORY, history)
                post_id = str(upload_instagram_reel(page, str(video), item['text'], append_store_link=False, thumb_offset=0))
                if not post_id.isdecimal():
                    raise RuntimeError('first_three_post_id_missing')
                record['post_id'] = post_id
                archive.save(HISTORY, history)
                observed = previews / (Path(item['name']).stem + '-instagram.jpg')
                evidence = thumbnail(page, post_id, observed)
                record['instagram_cover_distance'] = cover_distance(frame, observed, reference_is_frame=True)
                if (evidence.get('caption') != item['text'] or evidence.get('media_type') != 'VIDEO'
                        or not str(evidence.get('permalink', '')).startswith('https://www.instagram.com/')
                        or record['instagram_cover_distance'] > 0.12):
                    raise RuntimeError('published_instagram_cover_or_post_unverified')
                record.update(status='verified', permalink=evidence['permalink'])
                archive.save(HISTORY, history)
                print(f"FIRST_THREE_VERIFIED {item['name']} {post_id} {record['permalink']} cover_distance={record['instagram_cover_distance']:.4f}", flush=True)
                try:
                    record['telegram_attempted'] = True
                    archive.save(HISTORY, history)
                    send_telegram('✅ Instagram video yayımlandı', f"ToonZone · Sezon 1 · Bölüm {item['episode']} · Part {item['part']}/4\n{record['permalink']}")
                    record['telegram_ack'] = True
                except Exception:
                    record['telegram_ack'] = False
                archive.save(HISTORY, history)
        except Exception as exc:
            record['diagnostic'] = classify_meta_failure(exc)
            record['failure_type'] = type(exc).__name__
            archive.save(HISTORY, history)
            print(f"FIRST_THREE_STOPPED {item['name']} {type(exc).__name__} diagnostic={json.dumps(record['diagnostic'])}", flush=True)
            raise RuntimeError('first_three_stopped_before_next_part') from None
    print('FIRST_THREE_COMPLETE', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'publish'])
    mode = parser.parse_args().mode
    prepare(os.environ['GITHUB_RUN_ID']) if mode == 'prepare' else execute(os.environ['GITHUB_RUN_ID'])
