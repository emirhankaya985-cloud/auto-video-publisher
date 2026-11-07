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


def verify_publications(state, run_id, read_history):
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
        result.append(dict(key=key, post_id=post_id, status=status, reason=reason))
    return result


def verify_publications_with_retry(state, run_id, read_history, *, sleep=time.sleep):
    results = verify_publications(state, run_id, read_history)
    retryable = {'history_unavailable', 'not_observed_in_history_no_repost'}
    for delay in (5, 15):
        pending = {row['key']: state['entries'][row['key']] for row in results
                   if row['reason'] in retryable}
        if not pending:
            break
        sleep(delay)
        updated = {row['key']: row for row in verify_publications(
            {**state, 'entries': pending}, run_id, read_history
        )}
        results = [updated.get(row['key'], row) for row in results]
    return results


def _caption_digest(value):
    """Match publisher caption normalization without heavy media dependencies."""
    value = re.sub(r"https://www\\.etsy\\.com/\\S+", "", value or "")
    value = re.sub(r"\\bEtsy:\\s*", "", value, flags=re.I)
    return hashlib.sha256(" ".join(value.split()).encode()).hexdigest()


def audit_unresolved_remote(state, read_history):
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
        prior = row.get('failure') if isinstance(row.get('failure'), dict) else {}
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
        report['verification'] = verify_publications_with_retry(
            state, os.environ['GITHUB_RUN_ID'], history
        )
        report['previous_unresolved_remote'] = audit_unresolved_remote(state, history)
    report['checked_at'] = datetime.now(timezone.utc).isoformat()
    (args.root / 'operations-report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if any(r['status'] != 'verified' for r in report['verification']):
        reasons = Counter(row['reason'] for row in report['verification']
                          if row['status'] != 'verified')
        raise SystemExit(f'Publication verification incomplete; state preserved, no repost: {dict(reasons)}')


if __name__ == '__main__':
    main()
