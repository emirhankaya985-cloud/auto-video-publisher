"""One bounded owner-only inbox batch; archive offset BEFORE sending replies."""
import io
import json
import os
import sqlite3
import zipfile
from functools import cache
from pathlib import Path

import requests

from telegram_ai_worker import Worker, load_statistics, load_threads_statistics
from telegram_notifications import send_telegram
from telegram_status import status_table
from publication_github_progress import restore_publication_state

API = 'https://api.github.com/repos/emirhankaya985-cloud/auto-video-publisher/actions/'
ROOT = Path('status-runtime')


def restore_checkpoint(destination, *, get=requests.get):
    token = os.getenv('GITHUB_TOKEN', '')
    if not token:
        raise RuntimeError('checkpoint_read_access_missing')
    headers = {'Authorization': 'Bearer '+token, 'Accept': 'application/vnd.github+json'}
    response = get(API+'artifacts', headers=headers,
                   params={'name': 'telegram-status-checkpoint', 'per_page': 100},
                   timeout=20, allow_redirects=False)
    response.raise_for_status()
    artifacts = response.json().get('artifacts')
    if not isinstance(artifacts, list):
        raise RuntimeError('checkpoint_listing_invalid')
    eligible = [a for a in artifacts if a.get('name') == 'telegram-status-checkpoint'
                and a.get('expired') is False and type(a.get('id')) is int
                and (a.get('workflow_run') or {}).get('head_branch') == 'main']
    if not eligible:
        if artifacts:
            raise RuntimeError('checkpoint_unavailable_no_reset')
        return
    latest = max(eligible, key=lambda a: a['id'])
    response = get(API+f"artifacts/{latest['id']}/zip", headers=headers,
                   timeout=30, allow_redirects=True)
    response.raise_for_status()
    if len(response.content) > 2_000_000:
        raise RuntimeError('checkpoint_too_large')
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        if archive.namelist() != ['telegram.sqlite3'] or archive.infolist()[0].file_size > 2_000_000:
            raise RuntimeError('checkpoint_layout_invalid')
        data = archive.read('telegram.sqlite3')
    if not data.startswith(b'SQLite format 3\x00'):
        raise RuntimeError('checkpoint_format_invalid')
    destination.write_bytes(data)
    with sqlite3.connect(destination) as database:
        if database.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError('checkpoint_integrity_failed')


def prepare(*, session=requests):
    ROOT.mkdir(exist_ok=True)
    database = ROOT/'telegram.sqlite3'
    restore_checkpoint(database, get=session.get)
    # In a private Telegram chat, chat ID is the owner's user ID. Groups must
    # explicitly configure a human owner; never trust an arbitrary group member.
    chat = os.getenv('TELEGRAM_CHAT_ID', '')
    if not os.getenv('TELEGRAM_AI_OWNER_ID') and chat.isdecimal():
        os.environ['TELEGRAM_AI_OWNER_ID'] = chat
    os.environ['TELEGRAM_STATUS_ONLY'] = 'true'
    variables = json.loads(os.environ.get('PUBLISHER_VARS_JSON', '{}'))
    from telegram_status import FLAGS
    for flag in FLAGS:
        os.environ[flag] = str(variables.get(flag, ''))
    state = None
    loaded = False
    def status():
        nonlocal state, loaded
        if not loaded:
            try:
                state = restore_publication_state()
            except RuntimeError:
                state = None
            loaded = True
        return status_table(state=state, configured=True)
    messages = []
    def reserve(title, message, **kwargs):
        messages.append({'title': title, 'message': message, **kwargs})
    def reserve_callback_ack(callback_id):
        # No network call during prepare; the checkpoint is archived first.
        messages.append({'kind': 'callback_ack', 'callback_id': callback_id})

    @cache
    def statistics():
        return load_statistics(session=session)

    @cache
    def threads_statistics():
        return load_threads_statistics(session=session)

    worker = Worker(str(database), sender=reserve, status_loader=status,
                    statistics_loader=statistics,
                    threads_statistics_loader=threads_statistics,
                    callback_ack=reserve_callback_ack)
    (ROOT/'checkpoint-ready').write_text('valid', encoding='utf-8')
    try:
        if worker.db.execute("SELECT value FROM state WHERE key='inbox_blocked'").fetchone():
            raise RuntimeError('inbox_blocked_pending_review')
        response = session.get(worker.url+'getWebhookInfo', timeout=15, allow_redirects=False)
        response.raise_for_status()
        info = response.json()
        if info.get('ok') is not True or not isinstance(info.get('result', {}).get('url'), str) or info['result']['url']:
            if info.get('ok') is True and info.get('result', {}).get('url'):
                worker.db.execute("INSERT OR REPLACE INTO state VALUES ('inbox_blocked', 'webhook_active')")
                worker.db.commit()
            raise RuntimeError('webhook_active_or_unknown')
        response = session.get(worker.url+'getUpdates',
            params={'offset': worker.offset(), 'timeout': 0, 'limit': 20,
                    'allowed_updates': json.dumps(['message', 'callback_query'])}, timeout=15, allow_redirects=False)
        # In particular, a 409 is a competing-consumer incident, never retried.
        if response.status_code == 409:
            worker.db.execute("INSERT OR REPLACE INTO state VALUES ('inbox_blocked', 'consumer_conflict')")
            worker.db.commit()
            raise RuntimeError('consumer_conflict')
        response.raise_for_status()
        result = response.json()
        if result.get('ok') is not True or not isinstance(result.get('result'), list):
            raise RuntimeError('inbox_receipt_invalid')
        for update in sorted(result['result'], key=lambda u: u.get('update_id', -1)):
            worker.handle(update)
    finally:
        worker.db.close()
    (ROOT/'reserved-replies.json').write_text(json.dumps(messages), encoding='utf-8')
    print(json.dumps({'status': 'prepared', 'reserved_replies': len(messages),
                      'messages_sent': 0, 'publisher_writes': 0}))


def send(*, session=requests):
    messages = json.loads((ROOT/'reserved-replies.json').read_text(encoding='utf-8'))
    count = callback_count = callback_failures = 0
    reply_message_ids = []
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    from telegram_notifications import _BOT_TOKEN
    if any(isinstance(m, dict) and m.get('kind') == 'callback_ack' for m in messages):
        if not _BOT_TOKEN.fullmatch(token):
            raise RuntimeError('telegram_callback_token_unavailable')
    # ACK callback before reply; GitHub scheduled polls can be delayed.
    # Never retry either operation after an ambiguous network result.
    for message in messages:
        if isinstance(message, dict) and message.get('kind') == 'callback_ack':
            identifier = message.get('callback_id')
            if not isinstance(identifier, str) or not 1 <= len(identifier) <= 128:
                raise RuntimeError('telegram_callback_identifier_invalid')
            try:
                response = session.post(
                    'https://api.telegram.org/bot' + token + '/answerCallbackQuery',
                    json={'callback_query_id': identifier},
                    timeout=15, allow_redirects=False)
                if response.status_code != 200 or response.json().get('ok') is not True:
                    raise RuntimeError('telegram_callback_not_accepted')
            except Exception:
                # Scheduled GitHub polls can exceed Telegram's short callback
                # answer window. Never lose the owner's actual report because
                # the transient spinner acknowledgement has expired.
                callback_failures += 1
                continue
            callback_count += 1
    for message in messages:
        if isinstance(message, dict) and message.get('kind') == 'callback_ack':
            continue
        receipt = send_telegram(**message)
        if isinstance(receipt, dict) and type(receipt.get("message_id")) is int:
            reply_message_ids.append(receipt["message_id"])
        count += 1
    print(json.dumps({'server_acks': count, 'callback_server_acks': callback_count,
                      'callback_receipt_failures': callback_failures,
                      'reply_message_ids': reply_message_ids,
                      'phone_delivery_verified': False}))


if __name__ == '__main__':
    import sys
    try:
        if sys.argv[1:] == ['prepare']:
            prepare()
        elif sys.argv[1:] == ['send']:
            send()
        else:
            raise ValueError('expected prepare or send')
    except Exception as exc:
        # HTTP request URLs contain the bot token; never print tracebacks.
        print(json.dumps({'status': 'blocked', 'error_type': type(exc).__name__}))
        raise SystemExit(1) from None
