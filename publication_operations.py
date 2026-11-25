"""Read-only publication evidence, serial ledger and lossless checked backups.

Never changes publisher state, clears intents or uploads media. Backup restore is
explicit and refuses to overwrite any existing destination.
"""
import argparse
import hashlib
import io
import json
import os
import re
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def validate(state):
    if not isinstance(state, dict) or state.get('schema') != 1:
        raise ValueError('Invalid state schema')
    if not isinstance(state.get('entries'), dict):
        raise ValueError('Invalid entries')
    if any(not isinstance(row, dict) for row in state['entries'].values()):
        raise ValueError('Invalid entry')
    return state


def serial_identity(route, filename):
    stem = Path(filename).stem
    if route == 'toonzone':
        match = re.fullmatch(r'S(\d+)E(\d+)_(.+?)_Part_?(\d+)(?: \(\d+\))?', stem, re.I)
        if match:
            season, episode, title, part = match.groups()
            return f'S{int(season):02d}E{int(episode):02d}', int(part)
    elif route in {'film', 'film_second'}:
        match = re.fullmatch(r'(.+?)_Part_?(\d+)(?: \(\d+\))?', stem, re.I)
        if match:
            return re.sub(r'_+', ' ', match[1]).strip().casefold(), int(match[2])
    return None


def series_report(state):
    """Platform-scoped observed parts; filename aliases are never identity proof."""
    groups = defaultdict(lambda: defaultdict(list))
    invalid = []
    for key, row in validate(state)['entries'].items():
        route = row.get('route')
        if route not in {'film', 'film_second', 'toonzone'}:
            continue
        identity = serial_identity(route, str(row.get('file') or ''))
        if not identity:
            invalid.append(key)
            continue
        title, part = identity
        groups[(route, row.get('platform'), title)][part].append((key, row))
    result = []
    for (route, platform, title), parts in sorted(groups.items()):
        confirmed, blocked, conflicts = [], [], []
        for part, entries in sorted(parts.items()):
            ids = {str(r.get('post_id')) for _, r in entries
                   if r.get('status') == 'done' and r.get('post_id')}
            if ids:
                confirmed.append(part)
            else:
                blocked.append(part)
            if len(ids) > 1:
                conflicts.append(part)
        expected = set(range(1, 5 if route == 'toonzone' else max(parts) + 1))
        result.append(dict(route=route, platform=platform, series=title,
                           confirmed_parts=confirmed, held_parts=blocked,
                           missing_parts=sorted(expected - set(confirmed)),
                           conflicting_parts=conflicts,
                           scope='observed ledger; source inventory not exhaustive'))
    return {'series': result, 'unparsed_entries': invalid}


def create_backup(state_path, destination):
    raw = Path(state_path).read_bytes()
    validate(json.loads(raw))
    manifest = {'schema': 1, 'sha256': hashlib.sha256(raw).hexdigest(),
                'bytes': len(raw), 'created_at': datetime.now(timezone.utc).isoformat()}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('state.json', raw)
        archive.writestr('manifest.json', json.dumps(manifest))
    data = buf.getvalue()
    checked_backup(data)  # Verify before publishing the archive.
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as out:
        out.write(data)
    return manifest


def checked_backup(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sorted(archive.namelist()) != ['manifest.json', 'state.json']:
            raise ValueError('Unexpected archive members')
        if any(i.file_size > 100_000_000 for i in archive.infolist()):
            raise ValueError('Backup exceeds size limit')
        raw = archive.read('state.json')
        manifest = json.loads(archive.read('manifest.json'))
    if (manifest.get('schema') != 1 or manifest.get('bytes') != len(raw)
            or manifest.get('sha256') != hashlib.sha256(raw).hexdigest()):
        raise ValueError('Backup integrity mismatch')
    validate(json.loads(raw))
    return raw


def restore_backup(source, destination):
    raw = checked_backup(Path(source).read_bytes())
    with Path(destination).open('xb') as out:
        out.write(raw)


def exact_provider_video_verified(payload, *, page, platform, post_id, caption, now=None):
    """A provider video node proves original publication only with full identity.

    A matching caption or API success alone is insufficient. No write path.
    """
    if (not isinstance(payload, dict) or not str(post_id).isdecimal()
            or str(payload.get('id') or '') != str(post_id)
            or not isinstance(caption, str) or not caption.strip()):
        return False
    now = now or datetime.now(timezone.utc)
    date_value = payload.get('created_time') if platform == 'facebook' else payload.get('timestamp')
    try:
        when = datetime.fromisoformat(str(date_value).replace('Z', '+00:00'))
        if when.tzinfo is None:
            return False
        age = (now - when.astimezone(timezone.utc)).total_seconds()
        if not -600 <= age <= 172800:
            return False
    except (ValueError, TypeError, AttributeError):
        return False
    if platform == 'facebook':
        origin = payload.get('from')
        length = payload.get('length')
        if (not isinstance(origin, dict)
                or str(origin.get('id') or '') != str(page.get('page_id') or '')
                or payload.get('description') != caption
                or isinstance(length, bool)
                or not isinstance(length, (int, float, str))):
            return False
        try:
            return 0 < float(length) < 10800
        except (ValueError, TypeError):
            return False
    if platform == 'instagram':
        origin = payload.get('owner')
        if not isinstance(origin, dict):
            return False
        return (str(origin.get('id') or '') == str(page.get('instagram_id') or '')
                and payload.get('caption') == caption
                and payload.get('media_type') == 'VIDEO')
    return False


def verify_publications(state, run_id, read_history, read_exact=None):
    """Check exact post IDs in the expected account's video history, GET only.

    Missing from a bounded history means unverified, never absent/deleted or
    permission to repost. Results never downgrade or mutate the publisher ledger.
    """
    cache, result = {}, []
    for key, row in validate(state)['entries'].items():
        if str(row.get('run_id')) != str(run_id) or row.get('status') != 'done':
            continue
        route, platform = row.get('route'), row.get('platform')
        post_id = str(row.get('post_id') or '')
        status = 'unverified'
        reason = 'missing_post_id'
        if post_id and platform in {'facebook', 'instagram'}:
            pair = (route, platform)
            if pair not in cache:
                try:
                    rows = read_history(route, platform)
                    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
                        raise ValueError('Invalid history')
                    cache[pair] = {str(r['id']) for r in rows if r.get('id')}
                except Exception:
                    cache[pair] = None
            ids = cache[pair]
            if ids is None:
                reason = 'history_unavailable'
            elif post_id in ids:
                status, reason = 'verified', 'expected_account_video_history'
            else:
                reason = 'not_observed_in_history_no_repost'
            # Only a confirmed original post ID, exact Page owner, original
            # caption, video type and recent timestamp may bridge a moving
            # or lagging /videos feed. Any API rejection remains HELD.
            if status != 'verified' and read_exact is not None:
                try:
                    if read_exact(route, platform, post_id, row) is True:
                        status, reason = 'verified', 'exact_provider_video_id_owner_caption'
                except Exception:
                    pass
        result.append(dict(key=key, post_id=post_id, status=status, reason=reason))
    return result


def verify_publications_with_retry(state, run_id, read_history, *, read_exact=None, sleep=time.sleep):
    results = verify_publications(state, run_id, read_history, read_exact=read_exact)
    retryable = {'history_unavailable', 'not_observed_in_history_no_repost'}
    for delay in (5, 15):
        pending = {row['key']: state['entries'][row['key']] for row in results
                   if row['reason'] in retryable}
        if not pending:
            break
        sleep(delay)
        updated = {row['key']: row for row in verify_publications(
            {**state, 'entries': pending}, run_id, read_history, read_exact=read_exact
        )}
        results = [updated.get(row['key'], row) for row in results]
    return results


def _caption_digest(value):
    """Match publisher caption normalization without heavy media dependencies."""
    value = re.sub(r"https://www\.etsy\.com/\S+", "", value or "")
    value = re.sub(r"\bEtsy:\s*", "", value, flags=re.I)
    return hashlib.sha256(" ".join(value.split()).encode()).hexdigest()


def unresolved_source_evidence(key, row, all_entries):
    """Read-only source clues; cross-platform publication is never IG proof.

    A SHA256 is trustworthy only if both ledger entries persisted an identical
    digest. A filename match is explicitly weaker and never authorizes posts.
    """
    route, platform = row.get('route'), row.get('platform')
    proof = {'entry_fingerprint': hashlib.sha256(str(key).encode()).hexdigest()[:16],
             'source_sha256_present': False,
             'other_platform_exact_sha256_done': False,
             'other_platform_filename_candidate': False,
             'same_drive_item_other_platform_done': False,
             'same_drive_item_other_route_done': False,
             'same_source_held_sibling_pages': False}
    # The persisted ledger key binds route/platform to the original Drive ID.
    # This proves the same Drive *item*, never byte identity or an IG publish.
    key_parts = key.split(':', 2) if isinstance(key, str) else []
    original_drive_id = (key_parts[2] if len(key_parts) == 3
                         and key_parts[:2] == [route, platform]
                         and re.fullmatch(r'[A-Za-z0-9_-]{15,128}', key_parts[2])
                         else None)
    source = row.get('source_sha256')
    if isinstance(source, str) and re.fullmatch(r'[0-9a-f]{64}', source):
        proof['source_sha256_present'] = True
    else:
        source = None
    filename = row.get('file')
    if not isinstance(filename, str) or not filename or len(filename) > 150:
        filename = None
    for other_key, other in all_entries.items():
        if other is row or not isinstance(other, dict):
            continue
        parts = other_key.split(':', 2) if isinstance(other_key, str) else []
        same_drive = bool(original_drive_id and len(parts) == 3
                          and parts[2] == original_drive_id
                          and parts[:2] == [other.get('route'), other.get('platform')]
                          and other.get('file') == filename)
        if same_drive and other.get('status') == 'done' and str(other.get('post_id') or '').isdecimal():
            if other.get('platform') != platform:
                proof['same_drive_item_other_platform_done'] = True
            if other.get('route') != route:
                proof['same_drive_item_other_route_done'] = True
        if (route in {'film', 'film_second'} and other.get('route') in {'film', 'film_second'}
                and source and other.get('source_sha256') == source
                and other.get('status') == 'held' and other.get('platform') == platform):
            proof['same_source_held_sibling_pages'] = True
        if other.get('route') != route or other.get('platform') == platform:
            continue
        if other.get('status') != 'done' or not str(other.get('post_id') or '').isdecimal():
            continue
        if source and other.get('source_sha256') == source:
            proof['other_platform_exact_sha256_done'] = True
        elif filename and other.get('file') == filename:
            proof['other_platform_filename_candidate'] = True
    return proof


def audit_unresolved_remote(state, read_history, *, read_container=None):
    """GET-only candidate search; never resolves, mutates, or republishes an intent.

    A caption match is *not* a trustworthy source-video identity. A provider's
    bounded feed cannot prove a post is absent. Both conclusions remain held.
    """
    rows = [(key, row) for key, row in validate(state)['entries'].items()
            if row.get('status') in {'intent', 'uncertain', 'held'}]
    if len(rows) > 128:
        raise ValueError('too_many_unresolved_entries')
    allowed_routes = {'tarladaki', 'penguen', 'gonle', 'daily_laugh',
                      'film', 'film_second', 'toonzone'}
    cache, result = {}, []
    for key, row in rows:
        route, platform = row.get('route'), row.get('platform')
        entry = {'route': route if route in allowed_routes else 'unknown',
                 'platform': platform if platform in ('facebook', 'instagram') else 'unknown',
                 'status': row['status'], 'safe_to_repost': False}
        entry['source_evidence'] = unresolved_source_evidence(key, row, state['entries'])
        prior = row.get('failure') if isinstance(row.get('failure'), dict) else {}
        container_id = str(prior.get('container_id') or '')
        if (read_container is not None and platform == 'instagram'
                and route in allowed_routes and container_id.isdecimal()
                and len(container_id) <= 32):
            try:
                phase = read_container(route, container_id)
                if phase not in {'FINISHED', 'IN_PROGRESS', 'ERROR', 'EXPIRED', 'PUBLISHED'}:
                    phase = 'unverified'
            except Exception:
                phase = 'unverified'
            entry['existing_container_phase'] = phase
        if prior.get('reason') == 'visual_duplicate_review':
            entry['reason'] = 'visual_duplicate_requires_owner_review'
            result.append(entry)
            continue
        digest = row.get('caption_hash')
        if not isinstance(digest, str) or re.fullmatch(r'[0-9a-f]{64}', digest) is None:
            entry['reason'] = 'stored_caption_hash_missing'
            result.append(entry)
            continue
        pair = (route, platform)
        if route not in allowed_routes or platform not in ('facebook', 'instagram'):
            entry['reason'] = 'unsupported_route'
            result.append(entry)
            continue
        if pair not in cache:
            try:
                feed = read_history(route, platform)
                if not isinstance(feed, list) or any(not isinstance(item, dict) for item in feed):
                    raise ValueError('invalid_provider_feed')
                cache[pair] = feed
            except Exception:
                cache[pair] = None
        if cache[pair] is None:
            entry['reason'] = 'remote_history_unavailable'
        else:
            matches = {str(item.get('id')) for item in cache[pair]
                       if str(item.get('id', '')).isdecimal()
                       and _caption_digest(item.get('caption') or item.get('description') or '') == digest}
            if len(matches) == 1:
                entry['reason'] = 'caption_candidate_requires_source_proof'
                entry['candidate_post_id'] = next(iter(matches))
            elif matches:
                entry['reason'] = 'multiple_caption_candidates_need_review'
            else:
                entry['reason'] = 'not_observed_in_bounded_remote_history'
        result.append(entry)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('link-runtime'))
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--restore', type=Path)
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    if args.restore:
        if not args.destination:
            parser.error('--destination required for restore')
        restore_backup(args.restore, args.destination)
        return
    state_path = args.root / 'state.json'
    if not state_path.exists():
        raise SystemExit('No publisher state; no empty backup created')
    state = validate(json.loads(state_path.read_bytes()))
    # Always back up before attempting network reads, even on a failed publish.
    manifest = create_backup(state_path, args.root / 'operations-backup.zip')
    report = series_report(state)
    report['backup'] = manifest
    report['verification'] = []
    report['verification_scope'] = 'current-run Meta done entries only; YouTube uses existing bridge checks'
    if args.verify:
        from public_link_runtime import ROUTES, graph_rows
        from meta_auth_loader import load_meta_auth
        pages = None
        def history(route, platform):
            nonlocal pages
            if pages is None:
                pages = {p['page_name']: p for p in load_meta_auth()['pages']}
            return graph_rows(pages[ROUTES[route][1]], platform)
        def exact_receipt(route, platform, post_id, row):
            # Read-only direct Graph GET for a provider-acknowledged ID. The
            # token belongs to the original Page, never another actor.
            import requests
            from cloud_omnichannel_publisher import GRAPH_API_VERSION
            from publisher_recovery import read_with_retry
            nonlocal pages
            if pages is None:
                pages = {p['page_name']: p for p in load_meta_auth()['pages']}
            page = pages[ROUTES[route][1]]
            fields = ('id,description,from,length,created_time'
                      if platform == 'facebook'
                      else 'id,caption,owner,media_type,timestamp')
            response = read_with_retry(
                requests.get,
                f"https://graph.facebook.com/{GRAPH_API_VERSION}/{post_id}",
                headers={"Authorization": "Bearer " + page['page_token']},
                params={"fields": fields}, timeout=20,
                allow_redirects=False, graph_read=True)
            try:
                payload = response.json()
            finally:
                response.close()
            if response.status_code != 200 or not isinstance(payload, dict) or payload.get('error'):
                return False
            return exact_provider_video_verified(
                payload, page=page, platform=platform, post_id=post_id,
                caption=row.get('publish_caption'))
        report['verification'] = verify_publications_with_retry(
            state, os.environ['GITHUB_RUN_ID'], history, read_exact=exact_receipt
        )
        def container_phase(route, container_id):
            import requests
            from cloud_omnichannel_publisher import GRAPH_API_VERSION
            from publisher_recovery import read_with_retry
            nonlocal pages
            if pages is None:
                pages = {p['page_name']: p for p in load_meta_auth()['pages']}
            page = pages[ROUTES[route][1]]
            response = read_with_retry(
                requests.get,
                f"https://graph.facebook.com/{GRAPH_API_VERSION}/{container_id}",
                params={"fields": "status_code,status", "access_token": page['page_token']},
                timeout=20, allow_redirects=False, graph_read=True)
            if response.status_code != 200:
                raise RuntimeError("container_history_not_available")
            data = response.json()
            if not isinstance(data, dict) or str(data.get('id') or container_id) != container_id:
                raise RuntimeError("container_identity_mismatch")
            return data.get('status_code') or data.get('status')
        report['previous_unresolved_remote'] = audit_unresolved_remote(
            state, history, read_container=container_phase)
    report['checked_at'] = datetime.now(timezone.utc).isoformat()
    (args.root / 'operations-report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if any(r['status'] != 'verified' for r in report['verification']):
        reasons = Counter(row['reason'] for row in report['verification']
                          if row['status'] != 'verified')
        raise SystemExit(f'Publication verification incomplete; state preserved, no repost: {dict(reasons)}')


if __name__ == '__main__':
    main()
