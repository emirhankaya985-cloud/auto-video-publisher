"""Build a phone-readable ntfy digest without hiding required account totals."""

# The ntfy public service treats messages above 4096 UTF-8 bytes as attachments.
# Keep a margin for platform transport differences and avoid character splitting.
PHONE_BODY_LIMIT = 3800
_ACCOUNT_MARKERS = ("🎬 Yayın:", "📈 Bugün:", "👀 Genel:")
_TOTAL_MARKERS = ("🎯 Video hedefi:", "✅ Tamamlanan:", "❌ Eksik:",
                  "📈 BUGÜNKÜ TOPLAM:", "👀 GENEL TOPLAM:",
                  "🚨 Yayın hatası:", "🗄️ Geçmiş:")


def compact_phone_report(report: str, account_names, *, byte_limit: int = PHONE_BODY_LIMIT) -> str:
    """Preserve account daily/all-time views even for an oversized full report.

    Full report remains in GitHub Actions logs. Only optional verbose
    per-platform detail and repetitive error messages are removed. Every
    expected account must still have both required summary lines.
    """
    if len(report.encode("utf-8")) <= byte_limit:
        return report
    lines = report.splitlines()
    headers = {name.upper() for name in account_names}
    kept = [lines[0] if lines else "🌙 GÜNLÜK SOSYAL MEDYA RAPORU",
            "📱 Özet: ayrıntılar GitHub Actions gün sonu raporunda."]
    found = {}
    active = None
    in_global = False
    had_errors = False
    for original in lines[1:]:
        line = original.strip()
        if line in headers:
            active = line
            in_global = False
            if line not in found:
                found[line] = []
            continue
        if line.startswith("🏆 TÜM HESAPLARIN TOPLAMI"):
            active = None
            in_global = True
            kept.append("")
            kept.append(line)
            continue
        if line.startswith("⚠️ EKSİK VERİ / İZİN"):
            active = None
            in_global = False
            had_errors = True
            continue
        if active and line.startswith(_ACCOUNT_MARKERS):
            found[active].append(line)
        if in_global and line.startswith(_TOTAL_MARKERS):
            kept.append(line)
    # A new reporter format must not silently remove an account's critical
    # data. This would be especially misleading for a partially failed API.
    for name in account_names:
        header = name.upper()
        fields = found.get(header, [])
        if not any(row.startswith("📈 Bugün:") for row in fields):
            raise ValueError("ntfy compact report missing daily account figure")
        if not any(row.startswith("👀 Genel:") for row in fields):
            raise ValueError("ntfy compact report missing lifetime account figure")
    heading_count = 0
    output = kept[:2]
    for name in account_names:
        header = name.upper()
        output.append("")
        output.append(header)
        output.extend(found[header])
        heading_count += 1
    # Preserve the system-wide totals and collection warnings; a partial
    # total remains visibly marked as partial.
    output.extend(kept[2:])
    if had_errors:
        output.append("⚠️ Eksik veri / izin var; ayrıntılar GitHub Actions logunda.")
    compact = "\n".join(output)
    if len(compact.encode("utf-8")) > byte_limit:
        # Strip optional publication counts, never daily or all-time views.
        output = [line for line in output if not line.startswith("🎬 Yayın:")]
        compact = "\n".join(output)
    if len(compact.encode("utf-8")) > byte_limit:
        raise ValueError("ntfy compact report exceeds phone push limit")
    return compact
