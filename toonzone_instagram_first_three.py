"""Publish only the explicitly requested first three episodes with exact Drive covers."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import zipfile
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


def recovery_candidate(prior):
    """Read an independently finished upload-only probe; never create or publish."""
    from toonzone_first_three_upload_probe import NAMES as probe_names, WORKFLOW as probe_workflow
    candidate_history = archive.restore(names=probe_names, workflow_path=probe_workflow)
    candidate = candidate_history['records'].get('0' * 64, {})
    fields = ('file', 'user_id', 'source_id', 'source_sha256', 'cover_id', 'cover_sha256', 'caption')
    if (candidate.get('status') != 'finished_upload_only' or candidate.get('publish_allowed') is not False
            or candidate.get('candidate_profile') != 'toonzone_compact'
            or any(not isinstance(candidate.get(field), str) or not candidate[field] for field in fields)
            or any(candidate.get(field) != prior.get(field) for field in fields)
            or candidate.get('previous_container_id') != prior.get('diagnostic', {}).get('container_id')
            or not str(candidate.get('candidate_container_id', '')).isdecimal()
            or candidate.get('candidate_container_id') == candidate.get('previous_container_id')
            or not candidate.get('candidate_upload_sha256')
            or candidate.get('candidate_upload_sha256') == prior.get('upload_sha256')):
        raise RuntimeError('finished_upload_probe_does_not_match_failed_part')
    return candidate


def probe_frame(candidate, destination):
    """Retrieve the exact prepared first frame from the same upload-only run."""
    token = os.environ['GH_TOKEN']
    headers = {'Authorization': 'Bearer ' + token}
    run_id = str(candidate['intent_run_id'])
    if not run_id.isdecimal():
        raise RuntimeError('invalid_probe_run')
    root = f'https://api.github.com/repos/{archive.REPO}/actions'
    response = requests.get(f'{root}/runs/{run_id}/artifacts', headers=headers, timeout=30)
    response.raise_for_status()
    artifacts = [a for a in response.json()['artifacts']
                 if a['name'] == 'toonzone-first-three-upload-probe-cover' and not a.get('expired')]
    if len(artifacts) != 1:
        raise RuntimeError('probe_frame_archive_missing')
    response = requests.get(f"{root}/artifacts/{int(artifacts[0]['id'])}/zip", headers=headers, timeout=30)
    response.raise_for_status()
    if len(response.content) > 2_000_000:
        raise RuntimeError('probe_frame_archive_too_large')
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        if bundle.namelist() != ['prepared.jpg'] or bundle.getinfo('prepared.jpg').file_size > 2_000_000:
            raise RuntimeError('probe_frame_archive_invalid')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(bundle.read('prepared.jpg'))


def prepare(run_id, recovery=False):
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
        candidate = None
        if prior:
            if (prior.get('user_id') != user_id or prior.get('source_id') != item['id']
                    or prior.get('file') != item['name']):
                raise RuntimeError('first_three_previous_intent_unresolved')
            if prior.get('status') == 'verified' and str(prior.get('post_id')) in live:
                continue
            if not recovery or prior.get('post_id'):
                raise RuntimeError('first_three_previous_intent_unresolved')
            if prior.get('status') == 'attempted':
                if (item['episode'], item['part']) != (1, 1) or prior.get('diagnostic', {}).get('container_id') != '17911372950580142':
                    raise RuntimeError('unrecognized_attempt_cannot_be_replaced')
                if any(row.get('caption') == prior.get('caption') for row in live.values()):
                    raise RuntimeError('failed_part_now_exists_reconciliation_required')
                candidate = recovery_candidate(prior)
                current = graph_get(page, candidate['candidate_container_id'], 'id,status_code,status')
                if current.get('status_code') != 'FINISHED':
                    raise RuntimeError('probe_container_not_ready_for_first_publication')
            elif prior.get('status') != 'reserved' or prior.get('upload_sha256'):
                raise RuntimeError('unresolved_attempt_cannot_be_replaced')
        cover_name = Path(item['name']).stem + '.png'
        cover = covers.get(cover_name)
        if not cover:
            raise RuntimeError('exact_drive_cover_missing')
        path = download(cover['id'], ROOT / 'covers' / cover_name)
        if prior and (prior.get('cover_id') != cover['id'] or prior.get('cover_sha256') != digest(path)):
            raise RuntimeError('recovery_cover_changed')
        streams = probe(path).get('streams', [])
        if not any(stream.get('codec_type') == 'video' and stream.get('width', 0) > 0 for stream in streams):
            raise RuntimeError('exact_drive_cover_unreadable')
        text = text_for(item)
        if prior and prior.get('caption') != text:
            raise RuntimeError('recovery_caption_changed')
        record = dict(route='toonzone', platform='instagram', user_id=user_id,
                      source_id=item['id'], file=item['name'], cover_id=cover['id'],
                      cover_file=cover_name, cover_sha256=digest(path), caption=text,
                      status='reserved', intent_run_id=run_id, last_seen=archive.now_utc().isoformat())
        if prior:
            record['previous_intent'] = prior
        plan = dict(item, key=key, cover_path=str(path), text=text)
        if candidate:
            frame = ROOT / 'previews' / (Path(item['name']).stem + '-prepared.jpg')
            probe_frame(candidate, frame)
            if cover_distance(path, frame) > 0.12:
                raise RuntimeError('probe_frame_does_not_match_exact_cover')
            record.update(resume_container_id=candidate['candidate_container_id'],
                          source_sha256=candidate['source_sha256'], upload_sha256=candidate['candidate_upload_sha256'],
                          probe_run_id=candidate['intent_run_id'], probe_frame_sha256=digest(frame))
            plan['resume_frame'] = str(frame)
        history['records'][key] = record
        plans.append(plan)
    archive.save(HISTORY, archive.validate(history))
    archive.save(PLAN, dict(run_id=run_id, user_id=user_id, plans=plans,
                           upload_profile='toonzone_compact' if recovery else 'recovery_v3'))
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
    from cloud_omnichannel_publisher import create_instagram_cover_video, upload_instagram_reel, resume_instagram_container
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
                frame = previews / (Path(item['name']).stem + '-prepared.jpg')
                if record.get('resume_container_id'):
                    if str(frame) != item.get('resume_frame') or digest(frame) != record.get('probe_frame_sha256'):
                        raise RuntimeError('probe_frame_changed')
                else:
                    source = download_verified_publication_video(item['id'], temp / 'source.mp4')
                    record['source_sha256'] = digest(source)
                    covered = create_instagram_cover_video(source, Path(item['cover_path']), temp / 'covered.mp4', preserve_full_cover=True)
                    if data.get('upload_profile') == 'toonzone_compact':
                        video = prepare_instagram_upload(covered, temp / 'instagram.mp4', toonzone_compact=True)
                    else:
                        video = prepare_instagram_upload(covered, temp / 'instagram.mp4', force_transcode=True, recovery_v3=True)
                    subprocess.run(['ffmpeg', '-y', '-i', str(video), '-frames:v', '1', str(frame)],
                                   check=True, capture_output=True, timeout=60)
                    record['upload_sha256'] = digest(video)
                record['prepared_cover_distance'] = cover_distance(item['cover_path'], frame)
                if record['prepared_cover_distance'] > 0.12:
                    raise RuntimeError('prepared_first_frame_does_not_match_drive_cover')
                record['status'] = 'attempted'
                archive.save(HISTORY, history)
                if record.get('resume_container_id'):
                    post_id = resume_instagram_container(page, record['resume_container_id'],
                                                        before_publish=lambda: archive.save(HISTORY, history))
                    if post_id is None:
                        raise RuntimeError('probe_container_not_finished_before_publish')
                    post_id = str(post_id)
                else:
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
            from cloud_omnichannel_publisher import MetaAPIError
            if isinstance(exc, MetaAPIError):
                record['sanitized_meta_error'] = str(exc)
            archive.save(HISTORY, history)
            print(f"FIRST_THREE_STOPPED {item['name']} {type(exc).__name__} diagnostic={json.dumps(record['diagnostic'])}", flush=True)
            raise RuntimeError('first_three_stopped_before_next_part') from None
    print('FIRST_THREE_COMPLETE', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'prepare-recovery', 'publish'])
    mode = parser.parse_args().mode
    if mode in {'prepare', 'prepare-recovery'}:
        prepare(os.environ['GITHUB_RUN_ID'], recovery=mode == 'prepare-recovery')
    else:
        execute(os.environ['GITHUB_RUN_ID'])
