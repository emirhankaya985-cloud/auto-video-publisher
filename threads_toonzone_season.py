"""Owner-authorized, ordered first-season Threads campaign, 5 November 2026."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import tempfile

import publisher_alert_history as archive
from threads_live_publish import account_config, profile, publish, ready_media, error_label

WORKFLOW = '.github/workflows/threads_toonzone_season.yml'
ROOT = Path('toonzone-season-runtime')
HISTORY = ROOT / 'alert-history.json'
PLAN = ROOT / 'plan.json'
NAMES = ('toonzone-season-intent', 'toonzone-season-result')
PATTERN = re.compile(r'^S01E(\d{2})_.+_Part([1-4])\.mp4$')
CAMPAIGN = 'toonzone-season-one-2026-11-05'


def ordered_catalog(files):
    catalog = {}
    for name, item in files.items():
        match = PATTERN.fullmatch(name)
        if not match:
            continue
        slot = int(match[1]), int(match[2])
        if slot in catalog:
            raise RuntimeError('duplicate_season_part')
        catalog[slot] = dict(item, episode=slot[0], part=slot[1])
    expected = {(episode, part) for episode in range(1, 13) for part in range(1, 5)}
    if set(catalog) != expected:
        raise RuntimeError('first_season_catalog_incomplete')
    return [catalog[slot] for slot in sorted(catalog)]


def caption(episode, part):
    marker = f'ToonZone · S01E{episode:02d} · Part {part}/4'
    text = (f'Regular Show — Sürekli Dizi\n{marker}\n\n'
            '#RegularShow #SürekliDizi #ToonZone #Mordecai #Rigby '
            '#ÇizgiFilm #Animasyon #TürkçeDublaj #Komedi #KomikSahneler '
            '#Benson #Skips #Pops #Sezon1 '
            f'#Bölüm{episode} #S01E{episode:02d} #Part{part}')
    if len(text.encode('utf-8')) > 500:
        raise RuntimeError('season_caption_too_long')
    return text, marker


def prepare(run_id):
    from public_link_runtime import FOLDERS, inventory
    account = account_config('toonzone')
    user_id = profile(account)
    history = archive.restore(names=NAMES, workflow_path=WORKFLOW)
    catalog = ordered_catalog(inventory(FOLDERS['toonzone']))
    plans = []
    now = archive.now_utc().isoformat()
    for item in catalog:
        key = archive.identity(CAMPAIGN, 'toonzone', 'threads', item['id'])
        prior = history['records'].get(key)
        if prior:
            if (prior.get('status') != 'verified' or not prior.get('post_id')
                    or prior.get('user_id') != user_id or prior.get('file') != item['name']):
                raise RuntimeError('season_previous_intent_unresolved')
            continue
        text, marker = caption(item['episode'], item['part'])
        history['records'][key] = dict(route='toonzone', source_id=item['id'],
            file=item['name'], user_id=user_id, marker=marker, status='reserved',
            last_seen=now, intent_run_id=run_id)
        plans.append(dict(key=key, route='toonzone', text=text, **item))
    archive.save(HISTORY, archive.validate(history))
    archive.save(PLAN, dict(run_id=run_id, plans=plans))
    print(f'SEASON_RESERVED {len(plans)}', flush=True)


def execute(run_id):
    from public_link_runtime import download_verified_publication_video
    if os.getenv('THREADS_INTENT_ARCHIVED') != 'true':
        raise RuntimeError('season_intent_not_archived')
    data, history = archive.read(PLAN), archive.validate(archive.read(HISTORY))
    if data['run_id'] != run_id:
        raise RuntimeError('season_run_mismatch')
    account = account_config('toonzone')
    user_id = profile(account)
    for item in data['plans']:
        record = history['records'][item['key']]
        if (record['status'] != 'reserved' or record['intent_run_id'] != run_id
                or record['user_id'] != user_id or record['source_id'] != item['id']
                or record['file'] != item['name'] or record['marker'] not in item['text'].splitlines()):
            raise RuntimeError('season_reservation_mismatch')
        try:
            with tempfile.TemporaryDirectory(prefix='toonzone-season-') as directory:
                path = download_verified_publication_video(item['id'], Path(directory) / 'source.mp4')
                with path.open('rb') as source:
                    digest = hashlib.file_digest(source, 'sha256').hexdigest()
                url = ready_media(item['id'], digest)
            record['status'] = 'attempted'
            archive.save(HISTORY, history)
            record.update(publish(dict(url=url, text=item['text']), record, account))
            archive.save(HISTORY, history)
            print(f"SEASON_VERIFIED {item['name']} {record['post_id']} {record['permalink']}", flush=True)
        except Exception as exc:
            record['failure'] = error_label(exc)
            archive.save(HISTORY, history)
            print(f"SEASON_STOPPED {item['name']} {record['failure']}", flush=True)
            raise RuntimeError('season_stopped_before_next_part') from None
    print('SEASON_COMPLETE', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'publish'])
    mode = parser.parse_args().mode
    run_id = os.environ['GITHUB_RUN_ID']
    prepare(run_id) if mode == 'prepare' else execute(run_id)
