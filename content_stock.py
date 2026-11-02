"""Conservative platform inventory estimates; never allocates or publishes."""
from collections import defaultdict
from pathlib import Path
from publication_operations import serial_identity


def build_stock(catalogs, state, routes, daily_targets, *, unavailable=()):
    entries = state.get('entries', {})
    result = []
    for route, (source, label) in routes.items():
        if source in unavailable:
            result.append(dict(route=route, account=label, status='unavailable',
                               remaining=None, estimated_days=None))
            continue
        files = catalogs.get(source, {})
        videos = [v for n, v in files.items() if n.lower().endswith('.mp4')]
        # Name aliases share a slot but are not assumed to share file bytes.
        groups = defaultdict(list)
        for video in videos:
            identity = serial_identity(route, video['name'])
            groups[identity or ('source', video['id'])].append(video)
        series_parts = defaultdict(set)
        for identity in groups:
            if identity[0] != 'source':
                series_parts[identity[0]].add(identity[1])
        source_gaps = {title: sorted(set(range(1, 5 if route == 'toonzone'
                                       else max(parts) + 1)) - parts)
                       for title, parts in series_parts.items()}
        platforms = ('facebook',) if route == 'film_second' else ('facebook', 'instagram')
        for platform in platforms:
            counts = dict(remaining=0, completed=0, held=0, ambiguous=0, missing_txt=0)
            for identity, variants in groups.items():
                rows = [entries.get(f"{route}:{platform}:{v['id']}", {}) for v in variants]
                if any(r.get('status') == 'done' and r.get('post_id') for r in rows):
                    counts['completed'] += 1
                elif any(r.get('status') in {'intent', 'uncertain', 'done'} for r in rows):
                    counts['held'] += 1
                elif len(variants) != 1:
                    counts['ambiguous'] += 1
                elif (route in {'film', 'film_second', 'toonzone'}
                      and identity[0] == 'source'):
                    counts['ambiguous'] += 1
                elif source == 'humor' and any(
                    k.endswith(':' + variants[0]['id']) and r.get('route') != route
                    and r.get('route') in {'tarladaki', 'penguen'}
                    for k, r in entries.items()):
                    counts['held'] += 1
                elif Path(variants[0]['name']).with_suffix('.txt').name not in files:
                    counts['missing_txt'] += 1
                else:
                    counts['remaining'] += 1
            target = daily_targets[route]
            result.append(dict(route=route, account=label, platform=platform,
                               status='observed_candidates', **counts,
                               estimated_days=round(counts['remaining'] / target, 2),
                               daily_target=target,
                               low_stock=counts['remaining'] < target * 3,
                               missing_source_parts={k: v for k, v in source_gaps.items() if v},
                               caveat='TXT presence only; rights, captions, remote history and quality gates still required'))
    return result


def stock_markdown(rows):
    lines = ['## İçerik stoğu (aday kaynaklar; yayın garantisi değildir)', '',
             '| Hesap | Platform | Aday | Bekleyen | Tahmini gün |',
             '| --- | --- | --- | --- | --- |']
    for row in rows:
        if row['status'] == 'unavailable':
            lines.append(f"| {row['account']} | N/A | N/A | N/A | N/A |")
        else:
            lines.append(f"| {row['account']} | {row['platform']} | {row['remaining']} | {row['held']} | {row['estimated_days']} |")
    return '\n'.join(lines)
