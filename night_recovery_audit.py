"""Read existing provider state and source hashes. Never upload or mutate a ledger."""
import hashlib
import json
import tempfile
from pathlib import Path

from public_link_runtime import FOLDERS, ROUTES, download, inventory, restore
from meta_auth_loader import load_meta_auth
from toonzone_instagram_season import graph_get
from youtube_accepted_audit import audit as youtube_audit


def main():
    state = restore()
    report = {'uploads_attempted': 0, 'publication_state_modified': False,
              'youtube': youtube_audit(state), 'instagram_containers': [], 'film_sources': []}
    pages = {p['page_name']: p for p in load_meta_auth()['pages']}
    for row in state['entries'].values():
        failure = row.get('failure') or {}
        container = failure.get('container_id')
        if (row.get('status') != 'uncertain' or row.get('platform') != 'instagram'
                or not isinstance(container, str) or not container.isdigit()):
            continue
        item = {'route': row.get('route'), 'file': row.get('file'), 'container_id': container}
        try:
            page = pages[ROUTES[row['route']][1]]
            data = graph_get(page, container, 'id,status_code')
            status = data.get('status_code')
            item['status'] = status if status in {'IN_PROGRESS', 'FINISHED', 'PUBLISHED', 'ERROR', 'EXPIRED'} else 'unknown'
        except Exception:
            item['status'] = 'read_failed'
        report['instagram_containers'].append(item)
    files = inventory(FOLDERS['film'])
    names = ('Bickin_Part_3.mp4', 'Bickin_Part_3 (1).mp4',
             'Bickin_Part_8.mp4', 'Bickin_Part_8 (1).mp4')
    with tempfile.TemporaryDirectory() as directory:
        for index, name in enumerate(names):
            item = {'file': name, 'status': 'missing_from_current_inventory'}
            if name in files:
                try:
                    path = download(files[name]['id'], Path(directory) / f'{index}.mp4')
                    with path.open('rb') as stream:
                        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                    item.update(status='read', sha256=digest,
                                bytes=path.stat().st_size)
                except Exception:
                    item['status'] = 'source_read_failed'
            report['film_sources'].append(item)
    Path('night-recovery-audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
