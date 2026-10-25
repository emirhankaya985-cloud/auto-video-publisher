"""Conservative incident policy for the 985 Meta-only publisher.

Retry reads and media preparation, never a potentially completed Meta write.
Meta 400 may require video normalization, permissions, captions or API
parameters; classify it without assuming one specific fix.
"""
import time


READ_RETRY_HTTP = frozenset({429, 500, 502, 503, 504})
READ_RETRY_DELAYS = (1, 2)


def read_with_retry(get, *args, sleep=time.sleep, **kwargs):
    """Retry a read-only HTTP GET on throttling/server errors or transport errors.

    Never call this with a POST/PUT or media upload function. On permanent 4xx,
    return the response for the caller to refuse safely.
    """
    for attempt in range(3):
        try:
            response = get(*args, **kwargs)
        except OSError:
            # requests transport failures derive from OSError/IOError. A
            # programming bug must surface, not be silently retried.
            if attempt >= 2:
                raise
        else:
            if response.status_code not in READ_RETRY_HTTP or attempt >= 2:
                return response
        sleep(READ_RETRY_DELAYS[attempt])
    raise RuntimeError("Read retry unexpectedly exhausted")


def classify_meta_failure(exc):
    """Safe diagnostic category; *none* of these authorize reposting a video."""
    http = getattr(exc, "http_status", None)
    code = getattr(exc, "code", None)
    subcode = getattr(exc, "subcode", None)
    stage = getattr(exc, "stage", "unknown")
    if http in (401, 403) or code in (190, 10, 200):
        reason = "credentials_or_permissions"
    elif http == 429 or code in (4, 17, 32, 613):
        reason = "rate_limit"
    elif isinstance(http, int) and http >= 500:
        reason = "meta_server_or_network"
    elif http == 400:
        reason = "invalid_media_or_graph_request"
    else:
        reason = "unclassified_upload_result"
    return {
        "reason": reason,
        "stage": stage if isinstance(stage, str) and len(stage) < 80 else "unknown",
        "http_status": http if isinstance(http, int) else None,
        "graph_code": code if isinstance(code, int) else None,
        "graph_subcode": subcode if isinstance(subcode, int) else None,
        "post_write_action": "reconcile_with_remote_history_before_any_retry",
        "safe_to_repost": False,
    }


def confirmed_media_error_is_pre_publish(exc):
    """A no-write failure is only provable when local preparation threw it.

    Never infer no-write based on an HTTP 400 from an Instagram/FB endpoint.
    """
    return False

def known_pre_publish_media_rejection(exc, route, previous_retries=0):
    """Authorize one stricter *new preparation*, not a blind Meta repost.

    Binary-upload and processing errors in upload_instagram_reel() are raised
    before it ever executes media_publish. The Film/ToonZone compact uploads
    also qualify for ONE alternative standards-compliant encoding. A second
    failure, a publish-stage timeout, or missing stage evidence never qualifies. A failed media_publish or
    timeout may have published, so they NEVER qualify.
    """
    return bool(
        route in {"tarladaki", "penguen", "daily_laugh", "film", "toonzone"}
        and previous_retries == 0
        and getattr(exc, "stage", None) in {
            "Instagram ikili video aktarımı",
            "Instagram video işleme durumu",
        }
        and getattr(exc, "http_status", None) == 400
        and getattr(exc, "code", None) in (None, 100)
    )
