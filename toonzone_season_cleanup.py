"""Remove only posts recorded by the two owner-cancelled ToonZone campaigns."""
import argparse
import os
from pathlib import Path

import requests
import publisher_alert_history as archive
import threads_toonzone_season as threads_campaign
import toonzone_instagram_season as instagram_campaign
from threads_live_publish import THREADS, account_config, profile, rows

ROOT = Path('toonzone-cleanup-runtime')
MANIFEST = ROOT / 'deletion-manifest.json'
RESULT = ROOT / 'deletion-result.json'


def connection(platform):
    if platform == 'instagram':
        from cloud_omnichannel_publisher import GRAPH_API_VERSION
        page = instagram_campaign.page_for_toonzone()
        user_id = instagram_campaign.instagram_identity(page)
        return f'https://graph.facebook.com/{GRAPH_API_VERSION}', page['page_token'], user_id, page
    account = account_config('toonzone')
    return THREADS, account.token, profile(account), account


def owned_posts(platform, context):
    if platform == 'instagram':
        from public_link_runtime import graph_rows
        return graph_rows(context, 'instagram')
    return list(rows(THREADS, 'me/threads', context.token, 'id,text,media_type,permalink,timestamp'))


def targets(history, platform, user_id):
    result = []
    seen = set()
    for record in history['records'].values():
        post_id = str(record.get('post_id') or '')
        if not post_id:
            continue
        if (record.get('route') != 'toonzone' or record.get('user_id') != user_id
                or not post_id.isdecimal() or post_id in seen
                or not threads_campaign.PATTERN.fullmatch(record.get('file', ''))
                or record.get('status') not in {'verified', 'attempted'}):
            raise RuntimeError('cleanup_campaign_record_unverified')
        seen.add(post_id)
        result.append(dict(platform=platform, post_id=post_id, user_id=user_id,
                           file=record['file'], permalink=record.get('permalink'), status='reserved'))
    maximum = 11 if platform == 'instagram' else 48
    if len(result) > maximum:
        raise RuntimeError('cleanup_target_limit_exceeded')
    return result


def prepare(run_id):
    entries, errors = [], {}
    for platform, campaign in [('instagram', instagram_campaign), ('threads', threads_campaign)]:
        try:
            _base, _token, user_id, context = connection(platform)
            history = archive.restore(names=campaign.NAMES, workflow_path=campaign.WORKFLOW)
            selected = targets(history, platform, user_id)
            visible = {str(row['id']) for row in owned_posts(platform, context)}
            for item in selected:
                if item['post_id'] not in visible:
                    item['status'] = 'already_absent_from_profile'
                    item['absent_from_profile'] = True
            entries.extend(selected)
        except Exception as exc:
            errors[platform] = type(exc).__name__
    if not entries:
        raise RuntimeError('cleanup_no_verified_targets')
    archive.save(MANIFEST, dict(run_id=run_id, entries=entries, prepare_errors=errors))
    print('CLEANUP_RESERVED ' + str({p: sum(i['platform'] == p for i in entries)
                                   for p in ('instagram', 'threads')}), flush=True)


def delete_once(base, token, post_id):
    # One authenticated DELETE, with no blind retries and no redirected tokens.
    response = requests.delete(f'{base}/{post_id}',
        headers={'Authorization': 'Bearer ' + token}, timeout=30, allow_redirects=False)
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code == 200 and (data is True or isinstance(data, dict) and data.get('success') is True):
        return {'status': 'delete_accepted'}
    error = data.get('error', {}) if isinstance(data, dict) else {}
    return dict(status='delete_rejected', http_status=response.status_code,
                code=error.get('code') if type(error.get('code')) is int else None,
                subcode=error.get('error_subcode') if type(error.get('error_subcode')) is int else None)


def execute(run_id):
    if os.getenv('TOONZONE_DELETE_INTENT_ARCHIVED') != 'true':
        raise RuntimeError('cleanup_intent_not_archived')
    data = archive.read(MANIFEST)
    if data['run_id'] != run_id:
        raise RuntimeError('cleanup_run_mismatch')
    archive.save(RESULT, data)
    failed = bool(data['prepare_errors'])
    for platform in ('instagram', 'threads'):
        pending = [item for item in data['entries'] if item['platform'] == platform and item['status'] == 'reserved']
        if not pending:
            continue
        try:
            base, token, user_id, context = connection(platform)
            visible = {str(row['id']) for row in owned_posts(platform, context)}
            for item in pending:
                if item['user_id'] != user_id or not item['post_id'].isdecimal():
                    raise RuntimeError('cleanup_identity_changed')
                if item['post_id'] not in visible:
                    item['status'] = 'already_absent_from_profile'
                    archive.save(RESULT, data)
                    continue
                item['status'] = 'delete_attempted'
                archive.save(RESULT, data)
                item.update(delete_once(base, token, item['post_id']))
                archive.save(RESULT, data)
                print(f"CLEANUP_DELETE {platform} {item['post_id']} {item['status']} http={item.get('http_status')} code={item.get('code')}", flush=True)
                if item['status'] != 'delete_accepted':
                    failed = True
                    # A permission or provider rejection needs resolution first.
                    # Keep remaining IDs intact for authorized follow-through.
                    break
            remaining = {str(row['id']) for row in owned_posts(platform, context)}
            for item in data['entries']:
                if item['platform'] == platform:
                    item['absent_from_profile'] = item['post_id'] not in remaining
            archive.save(RESULT, data)
        except Exception as exc:
            failed = True
            data.setdefault('execution_errors', {})[platform] = type(exc).__name__
            archive.save(RESULT, data)
    for platform in ('instagram', 'threads'):
        items = [i for i in data['entries'] if i['platform'] == platform]
        print(f"CLEANUP_SUMMARY {platform} targets={len(items)} accepted={sum(i['status'] == 'delete_accepted' for i in items)} absent={sum(i.get('absent_from_profile', False) for i in items)}", flush=True)
    if failed:
        raise RuntimeError('cleanup_incomplete_check_recorded_api_rejection')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'delete'])
    mode = parser.parse_args().mode
    run_id = os.environ['GITHUB_RUN_ID']
    prepare(run_id) if mode == 'prepare' else execute(run_id)
