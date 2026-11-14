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

# Exact production evidence: 12 Nov run 43235604132, 14 Nov GET-only
# container audit 43571144382. Facebook Part17 already has a real post ID;
# this function touches only the original Instagram intent. OFF by default.
FILM17_SOURCE_ID = "1p_iGGksGhYlR6oSZLx25eZIP1s1CPVh7"
FILM17_FILENAME = "En_Buyuk_Saban_Part_17.mp4"
FILM17_SOURCE_SHA256 = "7b313a89102740f9a3249d89c55c70afccfa49b238ba9d07a1deb70f4810a14c"
FILM17_CAPTION_HASH = "dce6c862713aa3c5732690cfc1492488a4ab2058f18ad5249caefa66c264e2d8"
FILM17_CONTAINER_ID = "17906869221599675"
FILM17_ORIGIN_RUN = "43235604132"


def authorize_film_part17_expired_recovery(route, platform, item, entry, page, *,
                                           history_reconciled=False, get=None, environ=None):
    """Single exact-source IG recovery after live history GET and terminal GET.

    The special rescue switch is disabled by default, and the original
    uncertain receipt is retained. Never retry publish if it may have reached
    media_publish, or if the original container remains nonterminal.
    """
    import os
    env = os.environ if environ is None else environ
    if env.get("FILM_PART17_EXPIRED_RECOVERY_ENABLED", "").strip().lower() != "true":
        return False
    failure = entry.get("failure") if isinstance(entry, dict) else None
    if (history_reconciled is not True or route != "film" or platform != "instagram"
            or not isinstance(item, dict) or item.get("id") != FILM17_SOURCE_ID
            or item.get("name") != FILM17_FILENAME
            or not isinstance(entry, dict) or entry.get("route") != route
            or entry.get("platform") != platform or entry.get("file") != FILM17_FILENAME
            or entry.get("run_id") != FILM17_ORIGIN_RUN
            or entry.get("source_sha256") != FILM17_SOURCE_SHA256
            or entry.get("caption_hash") != FILM17_CAPTION_HASH
            or _caption_hash(entry.get("publish_caption")) != FILM17_CAPTION_HASH
            or entry.get("status") != "uncertain" or entry.get("post_id")
            or type(entry.get("prepublish_retry_count")) is not int
            or entry["prepublish_retry_count"] != 0
            or entry.get("container_publish_attempted")
            or entry.get("expired_container_recovery")
            or not isinstance(failure, dict)
            or failure.get("reason") != "invalid_media_or_graph_request"
            or failure.get("stage") != "Instagram ikili video aktarımı"
            or failure.get("http_status") != 400
            or failure.get("container_id") != FILM17_CONTAINER_ID
            or failure.get("safe_to_repost") is not False
            or failure.get("post_write_action") != "reconcile_with_remote_history_before_any_retry"
            or str(page.get("page_id")) != "1239298989276639"
            or str(page.get("instagram_id")) != "17841477990224124"
            or not page.get("page_token")):
        return False
    get = get or requests.get
    try:
        response = get(
            "https://graph.facebook.com/v24.0/" + FILM17_CONTAINER_ID,
            headers={"Authorization": "Bearer " + page["page_token"]},
            params={"fields": "status_code,status"}, timeout=20,
            allow_redirects=False,
        )
        body = response.json()
        if (response.status_code != 200 or not isinstance(body, dict)
                or body.get("error") or str(body.get("id", FILM17_CONTAINER_ID)) != FILM17_CONTAINER_ID
                or body.get("status_code") != "EXPIRED"):
            return False
    except (requests.RequestException, ValueError, TypeError):
        return False
    entry["expired_container_recovery"] = {
        "container_id": FILM17_CONTAINER_ID,
        "source_id": FILM17_SOURCE_ID,
        "source_sha256": FILM17_SOURCE_SHA256,
        "origin_run_id": FILM17_ORIGIN_RUN,
        "terminal_status": "EXPIRED",
        "no_media_publish_after_failed_binary_upload": True,
        "live_history_checked": True,
    }
    entry["status"] = "ready"
    entry["prepublish_retry_count"] = 1
    return True
