"""Conservative incident policy for the 985 Meta-only publisher.

Retry reads and media preparation, never a potentially completed Meta write.
Meta 400 may require video normalization, permissions, captions or API
parameters; classify it without assuming one specific fix.
"""
import time
from datetime import datetime, timedelta, timezone


READ_RETRY_HTTP = frozenset({429, 500, 502, 503, 504})
READ_RETRY_DELAYS = (1, 2)
GRAPH_READ_RETRY_CODES = frozenset({4, 17, 32, 613})

def bounded_retry_after(response, exponential_seconds):
    """Honor only short numeric Retry-After for GETs, never unbounded waits."""
    if response is None:
        return exponential_seconds
    headers = getattr(response, "headers", None)
    if headers is None or not hasattr(headers, "get"):
        return exponential_seconds
    raw = headers.get("Retry-After")
    if not isinstance(raw, str) or not raw.isdecimal() or len(raw) > 2:
        return exponential_seconds
    seconds = int(raw)
    return max(exponential_seconds, min(seconds, 8))



def _graph_read_is_throttled(response):
    # Meta can report throttling as HTTP 400. Only inspect this for explicitly
    # opted-in Graph reads; malformed media/auth errors must not be retried.
    if response.status_code != 400:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return type(code) is int and code in GRAPH_READ_RETRY_CODES


def read_with_retry(get, *args, sleep=time.sleep, graph_read=False, **kwargs):
    """Retry a read-only HTTP GET on throttling/server errors or transport errors.

    Never call this with a POST/PUT or media upload function. On permanent 4xx,
    return the response for the caller to refuse safely. graph_read=True also
    handles HTTP 400 carrying an explicit Graph throttling code, never arbitrary
    Graph errors or HTTP 200 application errors.
    """
    # Accidental use of a write method would bypass the intent ledger.
    # Refuse named POST/PUT/PATCH/DELETE functions before the first request.
    if getattr(get, "__name__", "").lower() in {"post", "put", "patch", "delete"}:
        raise ValueError("read_with_retry_requires_get")
    for attempt in range(3):
        retry_wait = READ_RETRY_DELAYS[attempt] if attempt < 2 else 0
        try:
            response = get(*args, **kwargs)
        except OSError:
            # requests transport failures derive from OSError/IOError. A
            # programming bug must surface, not be silently retried.
            if attempt >= 2:
                raise
        else:
            retryable = response.status_code in READ_RETRY_HTTP
            if graph_read and not retryable:
                retryable = _graph_read_is_throttled(response)
            if not retryable or attempt >= 2:
                return response
            retry_wait = bounded_retry_after(response, retry_wait)
            # Release pooled sockets before the next GET. The final response
            # stays open so its caller can still consume the body normally.
            close = getattr(response, "close", None)
            if callable(close):
                close()
        sleep(retry_wait)
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
    result = {
        "reason": reason,
        "stage": stage if isinstance(stage, str) and len(stage) < 80 else "unknown",
        "http_status": http if isinstance(http, int) else None,
        "graph_code": code if isinstance(code, int) else None,
        "graph_subcode": subcode if isinstance(subcode, int) else None,
        "post_write_action": "reconcile_with_remote_history_before_any_retry",
        "safe_to_repost": False,
    }
    container = getattr(exc, "container_id", None)
    status = getattr(exc, "container_status", None)
    if isinstance(container, str) and container.isdecimal() and len(container) <= 32:
        result["container_id"] = container
    if status in {"IN_PROGRESS", "FINISHED", "PUBLISHED", "ERROR", "EXPIRED", "UNVERIFIED"}:
        result["container_status"] = status
    return result


def confirmed_media_error_is_pre_publish(exc):
    """A no-write failure is only provable when local preparation threw it.

    Never infer no-write based on an HTTP 400 from an Instagram/FB endpoint.
    """
    return False

_TWO_ALTERNATE_PROFILE_ROUTES = frozenset({
    "tarladaki", "penguen", "daily_laugh", "gonle",
})
_ORDERED_ALTERNATE_PROFILE_ROUTES = frozenset({"film", "toonzone"})
ORDERED_RECOVERY_PROFILE_COUNT = 5
ORDERED_RECOVERY_WINDOW = timedelta(hours=2)
_PRE_PUBLISH_STAGES = frozenset({
    "Instagram ikili video aktarımı", "Instagram video işleme durumu",
})


def known_pre_publish_media_rejection(exc, route, previous_retries=0):
    """Allow the next Film/ToonZone profile after a proven no-publish IG 400.

    A short Reel can try the initial profile followed by two distinct
    validated local transcodes, on separate scheduled runs. Ordered Film and
    ToonZone rotate through validated profiles on later scheduled runs only
    when binary processing was definitively rejected before media_publish.

    This NEVER retries a timed-out POST, container creation, media_publish,
    a 401/403/limit error, or a return without a definite HTTP response.
    Every scheduled attempt first reconciles the platform's recent history.
    """
    if type(previous_retries) is not int or previous_retries < 0:
        return False
    if getattr(exc, "container_status", None) in {"PUBLISHED", "FINISHED", "IN_PROGRESS", "UNVERIFIED"}:
        return False
    if route in _TWO_ALTERNATE_PROFILE_ROUTES:
        allowed = previous_retries < 2
    elif route in _ORDERED_ALTERNATE_PROFILE_ROUTES:
        # Ordered series keep their current part at the head of the queue and
        # rotate through validated encodings on later scheduled runs.
        # This is still restricted to terminal, proven pre-publish rejection.
        allowed = True
    else:
        return False
    if not allowed or getattr(exc, "stage", None) not in _PRE_PUBLISH_STAGES:
        return False
    if getattr(exc, "http_status", None) != 400:
        return False
    code = getattr(exc, "code", None)
    subcode = getattr(exc, "subcode", None)
    return code in (None, 100) or (code == -1 and subcode in (2207001, 2207053))


def ordered_recovery_profile_index(retry_count):
    """Cycle ordered-series recoveries through five distinct media profiles."""
    if type(retry_count) is not int or retry_count < 0:
        raise ValueError("ordered retry count must be a nonnegative integer")
    return retry_count % ORDERED_RECOVERY_PROFILE_COUNT


def ordered_recovery_window(entry, now=None):
    """Whether an exact ordered-video 400 recovery is still inside its 2h window."""
    if not isinstance(entry, dict) or entry.get("status") != "ready":
        return False
    failure = entry.get("failure")
    if not isinstance(failure, dict) or failure.get("recovery_action") != "retry_same_ordered_video":
        return False
    if failure.get("http_status") != 400 or failure.get("stage") not in _PRE_PUBLISH_STAGES:
        return False
    if entry.get("container_publish_attempted") or failure.get("container_status") in {
            "PUBLISHED", "FINISHED", "IN_PROGRESS", "UNVERIFIED"}:
        return False
    code, subcode = failure.get("graph_code"), failure.get("graph_subcode")
    if not (code in (None, 100) or (code == -1 and subcode in (2207001, 2207053))):
        return False
    started = entry.get("recovery_started_at_utc")
    try:
        start = datetime.fromisoformat(started.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return False
    if start.tzinfo is None:
        return False
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        return False
    elapsed = now.astimezone(timezone.utc) - start.astimezone(timezone.utc)
    return timedelta(0) <= elapsed < ORDERED_RECOVERY_WINDOW
