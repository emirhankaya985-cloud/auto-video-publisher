"""Safe ntfy JSON delivery. HTTP acceptance is not phone delivery proof."""
import os
from urllib.parse import unquote, urlsplit, urlunsplit

import requests


MAX_NTFY_MESSAGE_BYTES = 4096


def _json_endpoint_and_topic():
    """Resolve a secret topic URL to the JSON root without exposing the topic."""
    topic_url = os.getenv("NTFY_TOPIC_URL", "").strip()
    legacy_topic = os.getenv("NTFY_TOPIC", "").strip()
    if not topic_url:
        if not legacy_topic:
            raise RuntimeError("NTFY_TOPIC_URL veya NTFY_TOPIC tanımlı değil.")
        if any(c in legacy_topic for c in "/?#") or any(ord(c) < 33 for c in legacy_topic):
            raise RuntimeError("NTFY_TOPIC biçimi geçersiz.")
        return "https://ntfy.sh/", legacy_topic

    try:
        url = urlsplit(topic_url)
        if (url.scheme not in {"https", "http"} or not url.netloc or
                url.username or url.password or url.query or url.fragment or
                url.hostname is None):
            raise ValueError("invalid")
        prefix, separator, encoded_topic = url.path.rstrip("/").rpartition("/")
        if not separator or not encoded_topic:
            raise ValueError("missing topic")
        topic = unquote(encoded_topic)
        if not topic or any(c in topic for c in "/?#") or any(ord(c) < 33 for c in topic):
            raise ValueError("invalid topic")
        endpoint = urlunsplit((url.scheme, url.netloc, prefix or "/", "", ""))
        return endpoint, topic
    except ValueError:
        # Do not expose the URL or topic name in errors.
        raise RuntimeError("NTFY_TOPIC_URL biçimi geçersiz.") from None


def _post(session, endpoint, payload, timeout, *, require_ack=False):
    try:
        response = session.post(
            endpoint, json=payload, timeout=timeout, allow_redirects=False
        )
        response.raise_for_status()
        # requests.raise_for_status() considers redirects successful. Refuse
        # redirects so a reverse proxy cannot forward our private topic.
        code = response.status_code
        if isinstance(code, int) and not 200 <= code < 300:
            raise RuntimeError("ntfy delivery not accepted (unexpected HTTP status)")
        if require_ack:
            # Validate ntfy's actual server receipt (not Android delivery).
            # Never include a response body or the private topic in errors.
            try:
                receipt = response.json()
            except (ValueError, TypeError):
                raise RuntimeError("ntfy server receipt missing or invalid") from None
            if (not isinstance(receipt, dict) or
                    receipt.get("event") != "message" or
                    receipt.get("topic") != payload["topic"] or
                    not isinstance(receipt.get("id"), str) or
                    not receipt["id"] or len(receipt["id"]) > 128):
                raise RuntimeError("ntfy server receipt mismatch") from None
            return {"http_status": code, "server_ack": True}
        # Production requests responses always carry an int. Existing mocked
        # publisher tests provide a synthetic response with no explicit status.
        return code
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        suffix = f" HTTP {status}" if isinstance(status, int) else ""
        # Never leak exception text: it may include a private topic or URL.
        raise RuntimeError(f"ntfy delivery failed{suffix} ({type(exc).__name__})") from None


def send_ntfy(title, message, *, priority=None, tags=None, timeout=15,
              session=requests, click=None, markdown=False, require_ack=False):
    """Send a single bounded JSON notification; never retry ambiguous POSTs."""
    endpoint, topic = _json_endpoint_and_topic()
    if not isinstance(message, str) or not isinstance(title, str):
        raise ValueError("ntfy title and message must be strings")
    if len(message.encode("utf-8")) > MAX_NTFY_MESSAGE_BYTES:
        # Oversized ntfy messages become attachments and may not appear as
        # push-body text on a phone. The reporter must compact its report.
        raise ValueError("ntfy message exceeds 4096 UTF-8 bytes")
    payload = {"topic": topic, "title": title, "message": message}
    if priority is not None:
        if type(priority) is not int or not 1 <= priority <= 5:
            raise ValueError("ntfy priority must be an integer from 1 through 5")
        payload["priority"] = priority
    if tags:
        payload["tags"] = list(tags)
    if click:
        try:
            url = urlsplit(click)
            if url.scheme not in {"https", "http"} or not url.netloc or url.username or url.password:
                raise ValueError("invalid")
        except ValueError:
            raise ValueError("ntfy click link must be an HTTP(S) URL") from None
        payload["click"] = click
    if markdown:
        payload["markdown"] = True
    return _post(session, endpoint, payload, timeout, require_ack=require_ack)
