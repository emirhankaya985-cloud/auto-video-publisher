"""Exact one-time recovery of an expired, provably never-published container."""
import hashlib
import re
import requests

SOURCE_ID = '1Zn8kYmexuUe3z1EKLtCrKFCwj4qVnIa2'
FILE_NAME = 'Avanak_Apti_Part_10 (1).mp4'
CONTAINER_ID = '17904577569599675'
CAPTION_HASH = 'd7bfd2238b0de47372e0536e61c79545049346aa56a7a75b0d5e707a342d1417'
BINDING = {'container_id': CONTAINER_ID, 'origin_run_id': '41036563337',
           'caption_hash': CAPTION_HASH, 'source_id': SOURCE_ID}
RECOVERY_PROOF = dict(BINDING, terminal_status='EXPIRED', no_publish_confirmed=True)


def _caption_hash(value):
    value = re.sub(r'https://www\.etsy\.com/\S+', '', value or '')
    value = re.sub(r'\bEtsy:\s*', '', value, flags=re.I)
    return hashlib.sha256(' '.join(value.split()).encode()).hexdigest()


def matches_exact_source(route, platform, item, entry):
    return (route == 'film' and platform == 'instagram'
            and item.get('id') == SOURCE_ID and item.get('name') == FILE_NAME
            and entry.get('route') == route and entry.get('platform') == platform
            and entry.get('file') == FILE_NAME and entry.get('caption_hash') == CAPTION_HASH
            and _caption_hash(entry.get('publish_caption')) == CAPTION_HASH)


def terminal_recovery_reserved(route, platform, item, entry):
    """A durable consumed reservation prevents rebinding the old container."""
    return (matches_exact_source(route, platform, item, entry)
            and entry.get('expired_container_recovery') == RECOVERY_PROOF
            and entry.get('prepublish_retry_count') == 3)


def authorize_exact_expired_recovery(route, platform, item, entry, page, *,
                                     history_reconciled=False, get=None):
    """One GET; state changes only with exact source + no-first-publish proof.

    Call only after successfully reading platform history and proving no exact
    or ambiguous caption match. Never use this to retry a media_publish POST.
    """
    if (history_reconciled is not True
            or not matches_exact_source(route, platform, item, entry)
            or entry.get('status') != 'uncertain'
            or type(entry.get('prepublish_retry_count')) is not int
            or entry['prepublish_retry_count'] != 2
            or entry.get('container_resume') != BINDING
            or entry.get('resume_no_publish_confirmed') is not True
            or entry.get('container_publish_attempted')
            or entry.get('expired_container_recovery')
            or str(page.get('page_id')) != '1239298989276639'
            or str(page.get('instagram_id')) != '17841477990224124'
            or not page.get('page_token')):
        return False
    get = get or requests.get
    try:
        response = get('https://graph.facebook.com/v24.0/' + CONTAINER_ID,
                       headers={'Authorization': 'Bearer ' + page['page_token']},
                       params={'fields': 'status_code,status'}, timeout=20,
                       allow_redirects=False)
        body = response.json()
        if (response.status_code != 200 or not isinstance(body, dict)
                or body.get('error') or str(body.get('id', CONTAINER_ID)) != CONTAINER_ID
                or body.get('status_code') != 'EXPIRED'):
            return False
    except (requests.RequestException, ValueError, TypeError):
        return False
    # Preserve immutable proof rather than deleting or resetting the old claim.
    entry['expired_container_recovery'] = dict(RECOVERY_PROOF)
    entry.pop('container_resume', None)
    entry['status'] = 'ready'
    entry['prepublish_retry_count'] = 3
    return True
