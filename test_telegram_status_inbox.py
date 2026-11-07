import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import telegram_status_inbox as inbox


class InboxTests(unittest.TestCase):
    env = {'TELEGRAM_BOT_TOKEN': '123456:'+'A'*30, 'TELEGRAM_CHAT_ID': '123456789',
           'GITHUB_TOKEN': 'test-only', 'PUBLISHER_VARS_JSON': '{}'}

    def response(self, data):
        return Mock(json=Mock(return_value=data), raise_for_status=Mock())

    def test_prepare_reserves_without_sending_and_persists_offset(self):
        update = {'update_id': 5, 'message': {'chat': {'id': 123456789},
                  'from': {'id': 123456789}, 'text': 'durum'}}
        session = Mock()
        session.get.side_effect = [self.response({'ok': True, 'result': {'url': ''}}),
                                  self.response({'ok': True, 'result': [update]})]
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, self.env, clear=True), \
                patch.object(inbox, 'ROOT', Path(temp)), patch.object(inbox, 'restore_checkpoint'), \
                patch.object(inbox, 'restore_publication_state', return_value={'entries': {}}), \
                patch.object(inbox, 'send_telegram') as send:
            inbox.prepare(session=session)
            send.assert_not_called()
            with sqlite3.connect(Path(temp)/'telegram.sqlite3') as db:
                self.assertEqual(db.execute("SELECT value FROM state WHERE key='offset'").fetchone()[0], '6')
            reserved = json.loads((Path(temp)/'reserved-replies.json').read_text())
            self.assertEqual(len(reserved), 1)
            self.assertEqual(reserved[0]['parse_mode'], 'HTML')
            self.assertTrue(reserved[0]['reply_markup']['is_persistent'])

    def test_statistics_keyboard_respects_owner_and_persisted_offset(self):
        def update(uid, owner):
            return {'update_id': uid, 'message': {'chat': {'id': 123456789},
                    'from': {'id': owner}, 'text': '📊 İstatistik'}}

        session = Mock()
        accepted = update(6, 123456789)
        session.get.side_effect = [self.response({'ok': True, 'result': {'url': ''}}),
                                  self.response({'ok': True, 'result': [update(5, 999), accepted, accepted]})]
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, self.env, clear=True), \
                patch.object(inbox, 'ROOT', Path(temp)), patch.object(inbox, 'restore_checkpoint'), \
                patch.object(inbox, 'load_statistics', return_value='Son arşiv ölçümü') as load, \
                patch.object(inbox, 'send_telegram') as send:
            inbox.prepare(session=session)
            send.assert_not_called()
            load.assert_called_once_with(session=session)
            with sqlite3.connect(Path(temp)/'telegram.sqlite3') as db:
                self.assertEqual(db.execute("SELECT value FROM state WHERE key='offset'").fetchone()[0], '7')
            inbox.send()
            send.assert_called_once_with(title='📊 İstatistik', message='Son arşiv ölçümü',
                                         reply_markup={
                                             'keyboard': [[{'text': '📊 İstatistik'}], [{'text': '🧵 Threads İstatistik'}]],
                                             'resize_keyboard': True, 'is_persistent': True})

    def test_inline_callback_is_reserved_before_API_ack_and_without_replay(self):
        update = {"update_id": 10, "callback_query": {
            "id": "callback123", "data": "owner:threads-stats:v1",
            "from": {"id": 123456789},
            "message": {"chat": {"id": 123456789, "type": "private"}}}}
        session = Mock()
        session.get.side_effect = [self.response({"ok": True, "result": {"url": ""}}),
                                  self.response({"ok": True, "result": [update]})]
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, self.env, clear=True), \
             patch.object(inbox, "ROOT", Path(temp)), patch.object(inbox, "restore_checkpoint"), \
             patch.object(inbox, "load_threads_statistics", return_value="Threads values"), \
             patch.object(inbox, "send_telegram") as sender:
            inbox.prepare(session=session)
            sender.assert_not_called()
            with sqlite3.connect(Path(temp)/"telegram.sqlite3") as db:
                self.assertEqual(db.execute("SELECT value FROM state WHERE key='offset'").fetchone()[0], "11")
            reserved = json.loads((Path(temp)/"reserved-replies.json").read_text())
            self.assertEqual(len(reserved), 2)
            self.assertEqual(reserved[1], {"kind": "callback_ack", "callback_id": "callback123"})
            sender_response = Mock(status_code=200)
            sender_response.json.return_value = {"ok": True, "result": True}
            session.post.return_value = sender_response
            inbox.send(session=session)
            session.post.assert_called_once()
            self.assertTrue(session.post.call_args.args[0].endswith("/answerCallbackQuery"))
            sender.assert_called_once()
            session.post.reset_mock()
            session.post.side_effect = TimeoutError("provider sensitive")
            with self.assertRaisesRegex(RuntimeError, "telegram_callback_receipt_unverified"):
                inbox.send(session=session)
            self.assertEqual(sender.call_count, 1)

    def test_existing_webhook_is_never_deleted_or_consumed(self):
        session = Mock()
        session.get.return_value = self.response({'ok': True, 'result': {'url': 'https://private.invalid'}})
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, self.env, clear=True), \
                patch.object(inbox, 'ROOT', Path(temp)), patch.object(inbox, 'restore_checkpoint'):
            with self.assertRaisesRegex(RuntimeError, 'webhook_active'):
                inbox.prepare(session=session)
            self.assertEqual(session.get.call_count, 1)
            session.post.assert_not_called()

    def test_group_without_explicit_owner_cannot_poll(self):
        session = Mock()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, dict(self.env, TELEGRAM_CHAT_ID='-100123456789'), clear=True), \
                patch.object(inbox, 'ROOT', Path(temp)), patch.object(inbox, 'restore_checkpoint'):
            with self.assertRaises(RuntimeError):
                inbox.prepare(session=session)
            session.get.assert_not_called()

    def test_consumer_conflict_latches_and_next_batch_does_not_poll(self):
        session = Mock()
        conflict = self.response({})
        conflict.status_code = 409
        session.get.side_effect = [self.response({'ok': True, 'result': {'url': ''}}), conflict]
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, self.env, clear=True), \
                patch.object(inbox, 'ROOT', Path(temp)), patch.object(inbox, 'restore_checkpoint'):
            with self.assertRaisesRegex(RuntimeError, 'consumer_conflict'):
                inbox.prepare(session=session)
            session.get.reset_mock()
            with self.assertRaisesRegex(RuntimeError, 'pending_review'):
                inbox.prepare(session=session)
            session.get.assert_not_called()
