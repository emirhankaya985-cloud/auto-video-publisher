"""Freeze next-day non-serial slots from corroborated platform observations."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TR = ZoneInfo('Europe/Istanbul')
ROUTES = {'tarladaki', 'penguen', 'gonle'}


def freeze_schedule(state, day, destination):
    """Persist the first policy/fallback for a day in the archived ledger."""
    import json
    from pathlib import Path
    target = Path(destination)
    policies = state.setdefault('adaptive_schedule_days', {})
    if day not in policies:
        try:
            policies[day] = json.loads(target.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            policies[day] = {}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(policies[day]), encoding='utf-8')


def build_schedule(recommendations, *, generated_at):
    if generated_at.tzinfo is None:
        raise ValueError('aware time required')
    slots = {}
    for route in sorted(ROUTES):
        platforms = {}
        for platform in ('facebook', 'instagram'):
            eligible = {}
            for row in recommendations:
                if not isinstance(row, dict) or row.get('route') != route or row.get('platform') != platform:
                    continue
                hour = row.get('hour_tr')
                score = row.get('engagement_per_1000_views')
                if (type(hour) is int and 8 <= hour <= 22
                        and type(row.get('posts')) is int and row['posts'] >= 4
                        and type(row.get('days')) is int and row['days'] >= 3
                        and type(score) in (int, float) and 0 <= score < 1_000_000):
                    eligible[hour] = score
            platforms[platform] = eligible
        common = set(platforms['facebook']) & set(platforms['instagram'])
        # All five slots require real observations on BOTH destinations.
        # With insufficient evidence, preserve all current slots.
        if len(common) >= 5:
            best = sorted(common, key=lambda h: (-min(platforms[p][h] for p in platforms), h))[:5]
            slots[route] = sorted(best)
    return {'schema': 1, 'generated_at': generated_at.isoformat(),
            'effective_date': (generated_at.astimezone(TR).date() + timedelta(days=1)).isoformat(),
            'slots': slots, 'serial_routes_changed': False}


def slots_for_route(document, route, now, original):
    """Reject stale, malformed, same-day or serial proposals as a whole."""
    if route not in ROUTES or not isinstance(document, dict) or document.get('schema') != 1:
        return original
    try:
        generated = datetime.fromisoformat(document['generated_at'])
        local = now.astimezone(TR)
        if (now.tzinfo is None or generated.tzinfo is None
                or document['effective_date'] != local.date().isoformat()
                or generated.astimezone(TR).date() != local.date() - timedelta(days=1)):
            return original
        hours = document['slots'][route]
        if (not isinstance(hours, list) or len(hours) != len(original) or len(hours) != 5
                or any(type(h) is not int or not 8 <= h <= 22 for h in hours)
                or hours != sorted(set(hours))):
            return original
        return [(h, original[i][1]) for i, h in enumerate(hours)]
    except (ValueError, KeyError, TypeError, AttributeError):
        return original


def restore_schedule(destination, *, token, now, get=None):
    """Read a successful main daily report artifact, no external writes."""
    import io
    import json
    import zipfile
    import requests
    from pathlib import Path
    get = get or requests.get
    target = Path(destination)
    target.unlink(missing_ok=True)
    if not token:
        return {'status': 'fallback', 'reason': 'read_token_missing'}
    base = 'https://api.github.com/repos/emirhankaya985-cloud/auto-video-publisher/actions/'
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'}
    try:
        response = get(base + 'workflows/daily_stats.yml/runs', headers=headers,
                       params={'branch': 'main', 'status': 'success', 'per_page': 5},
                       timeout=20, allow_redirects=False)
        response.raise_for_status()
        candidates = []
        for run in response.json()['workflow_runs']:
            if run.get('head_branch') != 'main' or run.get('conclusion') != 'success' or type(run.get('id')) is not int:
                continue
            response = get(base + f"runs/{run['id']}/artifacts", headers=headers, timeout=20, allow_redirects=False)
            response.raise_for_status()
            for artifact in response.json()['artifacts']:
                if artifact.get('name') != 'publish-time-recommendations' or artifact.get('expired') is not False or type(artifact.get('id')) is not int:
                    continue
                response = get(base + f"artifacts/{artifact['id']}/zip", headers=headers, timeout=30, allow_redirects=True)
                response.raise_for_status()
                if len(response.content) > 1_000_000:
                    continue
                with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                    info = archive.getinfo('time-recommendations.json')
                    if info.file_size > 1_000_000:
                        continue
                    document = json.loads(archive.read(info)).get('schedule', {})
                if (document.get('effective_date') == now.astimezone(TR).date().isoformat()
                        and isinstance(document.get('generated_at'), str)):
                    candidates.append(document)
        if not candidates:
            return {'status': 'fallback', 'reason': 'no_next_day_evidence'}
        # Earliest proposal for that day stays authoritative across reruns.
        document = min(candidates, key=lambda row: row['generated_at'])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document), encoding='utf-8')
        return {'status': 'restored', 'effective_date': document['effective_date']}
    except (requests.RequestException, ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile):
        return {'status': 'fallback', 'reason': 'schedule_evidence_unavailable'}
