import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import nvidia_assistant as ai
from telegram_ai_worker import Worker, compact_history, latest_evidence

ENV = {"NVIDIA_AI_ENABLED": "true", "NVIDIA_API_KEY": "secret-test-key",
       "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwx",
       "TELEGRAM_CHAT_ID": "123456789", "TELEGRAM_AI_OWNER_ID": "987654321"}


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_provider_request_fixed_endpoint_no_retry(self):
        session = Mock()
        session.post.return_value = Mock(status_code=200)
        session.post.return_value.json.return_value = {"choices": [{"message": {"content": "Ölçüm eksik."}}]}
        self.assertEqual(ai.answer("Dün?", {"day": "2026-10-27"}, session=session), "Ölçüm eksik.")
        args, options = session.post.call_args
        self.assertEqual(args, (ai.ENDPOINT,))
        self.assertFalse(options["allow_redirects"])
        self.assertEqual(options["json"]["model"], "nvidia/nemotron-3.5-super-vl-120b-a12b")
        self.assertEqual(options["json"]["chat_template_kwargs"], {"enable_thinking": False})
        self.assertNotIn("extra_body", options["json"])
        self.assertFalse(options["json"]["stream"])
        self.assertNotIn("tools", options["json"])
        self.assertEqual(session.post.call_count, 1)

    def test_other_model_override_has_no_nemotron_only_options(self):
        session = Mock()
        session.post.return_value = Mock(status_code=200)
        session.post.return_value.json.return_value = {"choices": [{"message": {"content": "Özet"}}]}
        with patch.dict(os.environ, {"NVIDIA_MODEL": "openai/gpt-oss-120b"}):
            ai.answer("Özet", {}, session=session)
        self.assertEqual(session.post.call_args.kwargs["json"]["model"], "openai/gpt-oss-120b")
        self.assertNotIn("chat_template_kwargs", session.post.call_args.kwargs["json"])

    def test_failure_redacts_provider_body_and_key(self):
        session = Mock()
        session.post.return_value = Mock(status_code=429, text="secret-test-key")
        with self.assertRaises(RuntimeError) as error:
            ai.answer("Özet", {}, session=session)
        self.assertNotIn("secret-test-key", str(error.exception))
        self.assertEqual(session.post.call_count, 1)

    def test_disabled_no_model_call(self):
        with patch.dict(os.environ, {"NVIDIA_AI_ENABLED": "false"}):
            session = Mock()
            with self.assertRaises(RuntimeError):
                ai.answer("Özet", {}, session=session)
            session.post.assert_not_called()
            self.assertFalse(ai.send_daily_summary({}))

    def test_empty_reasoning_only_response_rejected(self):
        session = Mock()
        session.post.return_value = Mock(status_code=200)
        session.post.return_value.json.return_value = {"choices": [{"message": {"content": None, "reasoning_content": "private reasoning"}}]}
        with self.assertRaises(RuntimeError):
            ai.answer("Özet", {}, session=session)

    def test_daily_summary_failure_does_not_break_tables(self):
        with patch.object(ai, "answer", side_effect=RuntimeError("secret-test-key")), patch("telegram_notifications.send_telegram") as send:
            self.assertFalse(ai.send_daily_summary({"day": "2026-10-27"}))
            send.assert_not_called()

    def test_daily_summary_uses_actual_day_plain_text(self):
        with patch.object(ai, "answer", return_value="<b>Özet</b>"), patch("telegram_notifications.send_telegram") as send:
            self.assertTrue(ai.send_daily_summary({"day": "2026-10-27"}))
            self.assertIn("2026-10-27", send.call_args.args[0])
            self.assertEqual(send.call_args.kwargs, {})

    def worker(self, directory):
        load = Mock(return_value={"latest_comparison": {"measured_at": "2026-10-27T23:42:00+03:00"}, "report_run": 123})
        model, sender = Mock(return_value="Gerçek kayıt özeti"), Mock()
        worker = Worker(str(Path(directory) / "state.sqlite3"), evidence_loader=load, model=model, sender=sender)
        self.addCleanup(worker.db.close)
        return worker, load, model, sender

    def update(self, uid=1, owner=987654321, chat=123456789, text="Dün nasıl?"):
        return {"update_id": uid, "message": {"from": {"id": owner}, "chat": {"id": chat}, "text": text}}

    def test_unauthorized_chat_or_sender_cannot_access_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker, load, model, sender = self.worker(tmp)
            worker.handle(self.update(owner=111))
            worker.handle(self.update(uid=2, chat=111))
            load.assert_not_called(); model.assert_not_called(); sender.assert_not_called()

    def test_duplicate_and_restart_do_not_resend(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker, load, model, sender = self.worker(tmp)
            worker.handle(self.update())
            worker.handle(self.update())
            worker2, load2, model2, sender2 = self.worker(tmp)
            worker2.handle(self.update())
            self.assertEqual(sender.call_count, 1)
            sender2.assert_not_called()

    def test_uncertain_delivery_never_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker, load, model, sender = self.worker(tmp)
            sender.side_effect = RuntimeError("send timeout")
            with self.assertRaises(RuntimeError):
                worker.handle(self.update())
            worker.handle(self.update())
            self.assertEqual(sender.call_count, 1)

    def test_no_evidence_no_model_and_explicit_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker, load, model, sender = self.worker(tmp)
            load.side_effect = RuntimeError("unavailable")
            worker.handle(self.update())
            model.assert_not_called()
            self.assertIn("tahmin etmedim", sender.call_args.args[1])

    def test_status_does_not_call_model_or_claim_live_measurement(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker, load, model, sender = self.worker(tmp)
            worker.handle(self.update(text="/durum"))
            model.assert_not_called()
            self.assertIn("2026-10-27", sender.call_args.args[1])
            self.assertIn("canlı anlık izlenme değildir", sender.call_args.args[1])

    def test_conversation_bounded_and_reset_preserves_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker, load, model, sender = self.worker(tmp)
            for uid in range(1, 6):
                worker.handle(self.update(uid))
            self.assertEqual(worker.db.execute("SELECT COUNT(*) FROM conversation").fetchone()[0], 6)
            worker.handle(self.update(6, text="/sifirla"))
            self.assertEqual(worker.offset(), 7)
            self.assertEqual(worker.db.execute("SELECT COUNT(*) FROM conversation").fetchone()[0], 0)

    def test_active_webhook_is_never_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker, *_ = self.worker(tmp)
            session = Mock()
            session.get.return_value = Mock(status_code=200)
            session.get.return_value.json.return_value = {"ok": True, "result": {"url": "https://existing.invalid"}}
            with self.assertRaises(RuntimeError):
                worker.run(session=session)
            self.assertEqual(session.get.call_count, 1)
            session.post.assert_not_called()

    def test_history_only_aggregate_no_captions_ids_or_unbounded_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            records = [{"period": f"2026-09-{i:02d}", "entity_type": "account", "metric": "lifetime_views", "value": i, "secret": "excluded"} for i in range(1, 32)]
            records.append({"entity_type": "video", "metric": "view_count", "entity_id": "private-id"})
            path.write_text("\n".join(json.dumps(r) for r in records))
            data = compact_history(path)
            self.assertEqual(len(data), 30)
            self.assertNotIn("excluded", json.dumps(data))
            self.assertNotIn("private-id", json.dumps(data))

    def test_missing_github_access_no_external_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Mock()
            with self.assertRaises(RuntimeError):
                latest_evidence(tmp, session=session)
            session.get.assert_not_called()

    def test_missing_owner_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"TELEGRAM_AI_OWNER_ID": ""}):
            with self.assertRaises(RuntimeError):
                self.worker(tmp)

    def report_session(self, *, branch="main", zip_name="account_views_comparison.json"):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w") as archive:
            archive.writestr(zip_name, json.dumps({"accounts": [], "measured_at": "2026-10-27T23:42:00+03:00"}))
        session = Mock()
        responses = [Mock(status_code=200), Mock(status_code=200), Mock(status_code=200, content=raw.getvalue())]
        responses[0].json.return_value = {"workflow_runs": [{"id": 42, "head_branch": branch, "conclusion": "success"}]}
        responses[1].json.return_value = {"artifacts": [{"name": "account-views-comparison", "expired": False, "id": 11}]}
        session.get.side_effect = responses
        return session

    def test_verified_report_source_and_old_measurement_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GITHUB_TOKEN": "test-read-token"}), patch("telegram_ai_worker.restore_history", return_value={"status": "first_snapshot"}):
            session = self.report_session()
            data = latest_evidence(tmp, session=session)
            self.assertEqual(data["report_run"], 42)
            self.assertIn("2026-10-27", data["latest_comparison"]["measured_at"])
            self.assertIn("yayın sonucu bulunmuyor", data["publication_status"])
            self.assertIn("/daily_stats.yml/runs", session.get.call_args_list[0].args[0])

    def test_non_main_report_is_rejected_before_download(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GITHUB_TOKEN": "test-read-token"}):
            session = self.report_session(branch="untrusted")
            with self.assertRaises(RuntimeError):
                latest_evidence(tmp, session=session)
            self.assertEqual(session.get.call_count, 1)

    def test_unexpected_archive_member_is_not_extracted(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GITHUB_TOKEN": "test-read-token"}):
            session = self.report_session(zip_name="../outside.json")
            with self.assertRaises(RuntimeError):
                latest_evidence(tmp, session=session)
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
