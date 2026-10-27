import os
import unittest
from datetime import date
from unittest.mock import Mock, patch

from views_comparison import ViewReport, build_comparison, telegram_tables, percentage
from telegram_notifications import send_telegram
import stats_reporter


def history(day, value, platform="Facebook", account="account", videos=None):
    videos = videos if videos is not None else {"123": value}
    base = {"account": account, "platform": platform, "period": day, "status": "ok",
            "measured_at": day + "T23:15:00+03:00"}
    return [dict(base, entity_type="account", metric="snapshot_status", value=len(videos)),
            dict(base, entity_type="account", metric="lifetime_views", value=value)] + [
                dict(base, entity_type="video", metric="view_count", entity_id=k, value=v)
                for k, v in videos.items()]


def compare(records=None, current=None, platforms=None, delayed=False, account="account"):
    return build_comparison(
        current if current is not None else {(account, "Facebook"): {"123": {"views": 125}}},
        records if records is not None else history("2026-10-26", 100) + history("2026-10-20", 80),
        {account: platforms or ["Facebook"]}, date(2026, 10, 27), "2026-10-27T18:30:00+03:00",
        delayed=delayed)


class ViewComparisonTests(unittest.TestCase):
    def test_actual_day_and_week_percentages_use_their_own_cumulative_baseline(self):
        data = compare()
        row = data["accounts"][0]
        self.assertEqual(row["daily"]["delta"], 25)
        self.assertEqual(row["daily"]["percent"], 25)
        self.assertEqual(row["weekly"]["delta"], 45)
        self.assertEqual(row["weekly"]["percent"], 56.25)
        self.assertEqual(data["baseline_dates"]["weekly"], "2026-10-20")

    def test_missing_week_is_unavailable_not_zero_or_nearest_day(self):
        data = compare(history("2026-10-26", 100) + history("2026-10-21", 70))
        self.assertIsNone(data["accounts"][0]["weekly"]["percent"])
        self.assertEqual(data["accounts"][0]["weekly"]["reason"], "geçmiş yok")
        self.assertIn("N/A", telegram_tables(data)[1][1])

    def test_zero_denominator_is_explicit_not_infinite_percent(self):
        data = compare(history("2026-10-26", 0, videos={"123": 0}))
        row = data["accounts"][0]["daily"]
        self.assertEqual(row["delta"], 125)
        self.assertIsNone(row["percent"])
        self.assertIn("taban sıfır", row["reason"])

    def test_small_positive_growth_is_not_rounded_to_apparent_zero(self):
        self.assertEqual(percentage(0.0025), "+0,0025%")

    def test_partial_telegram_delivery_fails_without_resending_accepted_part(self):
        report = ViewReport("short report", compare())
        with patch.object(stats_reporter, "send_ntfy", return_value={"http_status": 200}), \
                patch.object(stats_reporter, "telegram_configured", return_value=True), \
                patch.object(stats_reporter, "send_telegram", side_effect=[{"server_ack": True}, RuntimeError("failed")]) as send:
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                stats_reporter.notify(report)
        self.assertEqual(send.call_count, 2)

    def test_missing_platform_cannot_masquerade_as_complete_account_growth(self):
        data = compare(platforms=["Facebook", "Instagram"])
        row = data["accounts"][0]
        self.assertIsNone(row["total"])
        self.assertIsNone(row["daily"]["percent"])
        self.assertIsNone(data["total"])
        self.assertEqual(row["platforms"][0]["total"], 125)

    def test_two_platforms_aggregate_before_computing_percentage(self):
        current = {("account", "Facebook"): {"123": {"views": 125}},
                   ("account", "Instagram"): {"123": {"views": 60}}}
        data = compare(history("2026-10-26", 100) + history("2026-10-26", 50, "Instagram"),
                       current, ["Facebook", "Instagram"])
        row = data["accounts"][0]
        self.assertEqual(row["total"], 185)
        self.assertAlmostEqual(row["daily"]["percent"], 35 / 150 * 100)

    def test_missing_old_video_or_counter_correction_refuses_comparison(self):
        for videos in ({"123": 100, "missing": 20}, {"123": 150}):
            data = compare(history("2026-10-26", sum(videos.values()), videos=videos))
            self.assertIsNone(data["accounts"][0]["daily"]["delta"])
            self.assertEqual(data["accounts"][0]["total"], 125)

    def test_new_video_can_contribute_to_week_if_it_was_created_after_baseline(self):
        current = {("account", "Facebook"): {
            "123": {"views": 125}, "new": {"views": 20, "published_at": "2026-10-23T10:00:00+03:00"}}}
        row = compare(history("2026-10-20", 80), current)["accounts"][0]
        self.assertEqual(row["weekly"]["delta"], 65)
        current[("account", "Facebook")]["new"]["published_at"] = "2026-10-19T10:00:00+03:00"
        row = compare(history("2026-10-20", 80), current)["accounts"][0]
        self.assertIsNone(row["weekly"]["delta"])

    def test_partial_baseline_and_delayed_measurement_do_not_invent_growth(self):
        rows = history("2026-10-26", 100)
        rows.pop()
        self.assertIsNone(compare(rows)["accounts"][0]["daily"]["percent"])
        self.assertIsNone(compare(delayed=True)["accounts"][0]["daily"]["percent"])

    def test_html_escapes_labels_and_keeps_three_bounded_parts_for_six_accounts(self):
        names = list(stats_reporter.ACCOUNT_TARGETS)
        names[0] += " <tag>&"
        snapshot = {(name, p): {"123": {"views": 10**12}} for name in names
                    for p in ("Facebook", "Instagram")}
        data = build_comparison(snapshot, [], {n: ["Facebook", "Instagram"] for n in names},
                                date(2026, 10, 27), "2026-10-27T18:30:00+03:00")
        messages = telegram_tables(data)
        self.assertEqual(len(messages), 3)
        for title, text in messages:
            self.assertLessEqual(len((title + text).encode("utf-16-le")) // 2, 3800)
            self.assertNotIn("<tag>", text)
        self.assertIn("&lt;tag&gt;&amp;", messages[0][1])

    def test_notify_sends_three_detailed_messages_instead_of_truncated_compact_body(self):
        report = ViewReport("short report", compare())
        with patch.object(stats_reporter, "send_ntfy", return_value={"http_status": 200}), \
                patch.object(stats_reporter, "telegram_configured", return_value=True), \
                patch.object(stats_reporter, "send_telegram", return_value={"server_ack": True}) as send:
            stats_reporter.notify(report)
        self.assertEqual(send.call_count, 3)
        self.assertTrue(all(c.kwargs["parse_mode"] == "HTML" for c in send.call_args_list))

    def test_html_transport_adds_parse_mode_and_refuses_truncated_markup(self):
        env = {"TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwx", "TELEGRAM_CHAT_ID": "123456789"}
        transport = Mock()
        transport.post.return_value = Mock(status_code=200, json=lambda: {"ok": True, "result": {"message_id": 1}})
        with patch.dict(os.environ, env, clear=True):
            send_telegram("A & B", "<pre>safe</pre>", parse_mode="HTML", session=transport)
            payload = transport.post.call_args.kwargs["json"]
            self.assertEqual(payload["parse_mode"], "HTML")
            self.assertIn("A &amp; B", payload["text"])
            with self.assertRaises(ValueError):
                send_telegram("hi", "<pre>" + "x" * 4000 + "</pre>", parse_mode="HTML", session=transport)
        self.assertEqual(transport.post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
