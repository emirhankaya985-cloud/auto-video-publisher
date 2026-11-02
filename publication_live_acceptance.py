"""Explicit main-only acceptance: provider GETs and local media checks only."""
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo


def main():
    import public_link_runtime as runtime
    from publication_operations import verify_publications
    from publication_github_progress import restore_publication_state
    from media_quality import inspect_video
    from performance_history import collect_engagement
    from stats_reporter import META_TARGETS, get_meta_page_info, graph_get, graph_pages
    root = runtime.ROOT
    root.mkdir(exist_ok=True)
    results = {}
    failures = []
    # Keep the downloaded authoritative ledger separate from audit-local state.
    original = restore_publication_state()
    try:
        runtime.plan(audit=True)
        stock = json.loads((root / 'content-stock.json').read_text())
        results['stock'] = {'accounts': len(stock['accounts']),
                            'unavailable': sum(r['status'] == 'unavailable' for r in stock['accounts'])}
        if results['stock']['unavailable']:
            failures.append('stock_sources_unavailable')
    except Exception as exc:
        failures.append('stock_audit_failed')
        results['stock'] = {'error_type': type(exc).__name__}
    eligible = [(k, r) for k, r in original['entries'].items()
                if r.get('status') == 'done' and r.get('post_id')
                and str(r.get('run_id', '')).isdecimal()]
    if eligible:
        run_id = max((r['run_id'] for _, r in eligible), key=lambda x: int(x))
        pages = {p['page_name']: p for p in runtime.load_meta_auth()['pages']}
        def history(route, platform):
            return runtime.graph_rows(pages[runtime.ROUTES[route][1]], platform)
        results['posts'] = verify_publications(original, run_id, history)
        results['source_run_id'] = run_id
        if not results['posts'] or any(r['status'] != 'verified' for r in results['posts']):
            failures.append('posts_unverified')
        key, row = next((k, r) for k, r in eligible if r['run_id'] == run_id)
        source = key.split(':', 2)[2]
        try:
            path = runtime.download(source, root / 'acceptance-source.mp4')
            results['quality'] = inspect_video(path)
        except Exception as exc:
            results['quality'] = {'status': 'unverified', 'error_type': type(exc).__name__}
            failures.append('quality_unverified')
        finally:
            (root / 'acceptance-source.mp4').unlink(missing_ok=True)
    else:
        failures.append('no_post_ids_for_acceptance')
    now = datetime.now(ZoneInfo('Europe/Istanbul'))
    records, errors = collect_engagement(META_TARGETS, get_meta_page_info, graph_get, graph_pages,
        measured_at=now.isoformat(), period=now.date().isoformat())
    results['engagement'] = {'records': len(records), 'errors': errors,
        'unavailable': sum(r['status'] != 'ok' for r in records),
        'followers_verified': sum(r['metric'] == 'followers' and r['status'] == 'ok' for r in records)}
    runtime.save(root / 'engagement-preview.json', records)
    if errors or results['engagement']['unavailable']:
        failures.append('engagement_partial')
    results.update(failures=failures, publishing_attempted=False,
                   status='verified' if not failures else 'partial')
    runtime.save(root / 'live-acceptance.json', results)
    print(json.dumps({k: v for k, v in results.items() if k != 'posts'}, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
