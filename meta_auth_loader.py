"""Read-only Meta discovery; credentials remain in process memory."""
import json
import os
import time
from pathlib import Path
import requests
from publisher_recovery import read_with_retry

ALLOWED_NAMES = {n.casefold() for n in ('Tarladaki Fasulye', 'Beyinsiz Penguen',
    'Gönle Düşen', 'Daily Laugh Lab', 'Film Mağarası', 'Filmmagrasi', 'ToonZone')}
KNOWN_IDS = {'1239298989276639': 'Film Mağarası', '854990964375370': 'Filmmagrasi',
             '1298191963387372': 'ToonZone'}


def discover_pages(token, *, get=None):
    get = get or requests.get
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError('META_ACCESS_TOKEN eksik')
    url = 'https://graph.facebook.com/v24.0/me/accounts'
    pages, ids, names, cursors = [], set(), set(), set()
    params = {'fields': 'id,name,access_token,instagram_business_account{id,username}', 'limit': 100}
    for _ in range(30):
        try:
            response = read_with_retry(
                get, url, headers={'Authorization': f'Bearer {token.strip()}'},
                params=dict(params), timeout=20, allow_redirects=False,
                graph_read=True, sleep=time.sleep,
            )
            body = response.json()
        except Exception:
            raise RuntimeError('Meta hesap sorgusu tamamlanamadı') from None
        if response.status_code != 200 or not isinstance(body, dict) or body.get('error'):
            error = body.get('error', {}) if isinstance(body, dict) else {}
            code = error.get('code') if isinstance(error, dict) else None
            safe_code = str(code) if isinstance(code, int) and 0 <= code <= 999999 else 'unknown'
            subcode = error.get('error_subcode') if isinstance(error, dict) else None
            safe_subcode = str(subcode) if isinstance(subcode, int) and 0 <= subcode <= 999999 else 'unknown'
            # The Graph message, URL and all credential material are untrusted.
            # Numeric subcodes distinguish expiry from revoked/changed grants;
            # never try a new upload or label a failed read as published.
            raise RuntimeError(
                f'Meta hesap erişimi reddedildi '
                f'(HTTP {response.status_code}, kod {safe_code}, alt_kod {safe_subcode})'
            )
        if not isinstance(body.get('data'), list):
            raise RuntimeError('Meta hesap yanıtı geçersiz')
        for row in body['data']:
            if not isinstance(row, dict):
                raise RuntimeError('Meta hesap kaydı geçersiz')
            pid, name = str(row.get('id') or ''), str(row.get('name') or '').strip()
            if pid in KNOWN_IDS:
                name = KNOWN_IDS[pid]
            elif name.casefold() not in ALLOWED_NAMES:
                continue
            if name.casefold() in {n.casefold() for n in KNOWN_IDS.values()} and pid not in KNOWN_IDS:
                raise RuntimeError('Meta sabit sayfa kimliği eşleşmedi')
            ig, page_token = row.get('instagram_business_account') or {}, row.get('access_token')
            if (not pid.isdecimal() or not isinstance(page_token, str) or not page_token.strip()
                    or not isinstance(ig, dict) or (ig.get('id') and not str(ig['id']).isdecimal())):
                raise RuntimeError('Meta sayfa kimliği veya sayfa tokenı eksik/geçersiz')
            if pid in ids or name.casefold() in names:
                raise RuntimeError('Meta hesap eşleşmesi tekil değil')
            ids.add(pid)
            names.add(name.casefold())
            pages.append({'page_id': pid, 'page_name': name, 'page_token': page_token,
                          'instagram_id': ig.get('id'), 'instagram_username': ig.get('username')})
        paging = body.get('paging') or {}
        if not isinstance(paging, dict):
            raise RuntimeError('Meta sayfalama yanıtı geçersiz')
        if not paging.get('next'):
            return {'pages': pages}
        cursor = (paging.get('cursors') or {}).get('after')
        if not isinstance(cursor, str) or not cursor or cursor in cursors:
            raise RuntimeError('Meta sayfalama tamamlanamadı')
        cursors.add(cursor)
        params['after'] = cursor
    raise RuntimeError('Meta hesap listesi sınırı aşıldı')


def load_meta_auth():
    raw = os.getenv('META_AUTH_JSON', '').strip()
    if raw:
        return json.loads(raw)
    path = Path(__file__).with_name('meta_auth.json')
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return discover_pages(os.getenv('META_ACCESS_TOKEN', ''))
