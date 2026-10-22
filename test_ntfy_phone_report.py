import unittest

from ntfy_phone_report import PHONE_BODY_LIMIT, compact_phone_report


ACCOUNTS = [
    "🌱 Tarladaki Fasulye",
    "🐧 Beyinsiz Penguen",
    "❤️ Gönle Düşen",
    "😂 Daily Laugh Lab",
    "🎬 Film Mağarası + Filmmagrasi",
    "📺 ToonZone",
]


class PhoneReportTests(unittest.TestCase):
    def make_long_report(self):
        lines = ["🌙 GÜNLÜK SOSYAL MEDYA RAPORU — 20.10.2026", ""]
        for idx, name in enumerate(ACCOUNTS):
            lines.extend([
                name.upper(),
                f"🎬 Yayın: {idx}/8 ⚠️",
                f"📈 Bugün: Kısmi: +{idx + 11}",
                f"👀 Genel: Kısmi: {123456 + idx}",
            ])
            lines.extend(["  Instagram: Yayın hata ayrıntıları ... " + "⛔" * 80] * 20)
            lines.append("")
        lines.extend([
            "🏆 TÜM HESAPLARIN TOPLAMI",
            "🎯 Video hedefi: 32",
            "📈 BUGÜNKÜ TOPLAM: Kısmi: +432",
            "👀 GENEL TOPLAM: Kısmi: 4.000.000",
            "🚨 Yayın hatası: 3",
            "🗄️ Geçmiş: ⚠️ Drive arşivi kaydedilemedi",
            "⚠️ EKSİK VERİ / İZİN:",
        ])
        lines.extend(["• HTTP 403 " + "⛔" * 100] * 100)
        return "\n".join(lines)

    def test_long_report_preserves_all_six_daily_and_lifetime_totals(self):
        original = self.make_long_report()
        self.assertGreater(len(original.encode("utf-8")), 4096)
        output = compact_phone_report(original, ACCOUNTS)
        self.assertLessEqual(len(output.encode("utf-8")), PHONE_BODY_LIMIT)
        for idx, name in enumerate(ACCOUNTS):
            self.assertIn(name.upper(), output)
            self.assertIn(f"📈 Bugün: Kısmi: +{idx + 11}", output)
            self.assertIn(f"👀 Genel: Kısmi: {123456 + idx}", output)
        self.assertIn("📈 BUGÜNKÜ TOPLAM: Kısmi: +432", output)
        self.assertIn("👀 GENEL TOPLAM: Kısmi: 4.000.000", output)
        self.assertIn("⚠️ Eksik veri", output)
        self.assertNotIn("⛔" * 80, output)

    def test_short_report_is_preserved_exactly(self):
        original = "🌙 Rapor\n👀 Genel: 2.569"
        self.assertEqual(compact_phone_report(original, ACCOUNTS), original)

    def test_missing_daily_account_line_never_produces_misleading_summary(self):
        report = self.make_long_report().replace("📈 Bugün: Kısmi: +11", "Günlük veri yok")
        with self.assertRaisesRegex(ValueError, "daily account figure"):
            compact_phone_report(report, ACCOUNTS)

    def test_byte_limit_counts_utf8_not_character_count(self):
        report = self.make_long_report()
        result = compact_phone_report(report, ACCOUNTS)
        self.assertLessEqual(len(result.encode("utf-8")), PHONE_BODY_LIMIT)


if __name__ == "__main__":
    unittest.main()
