"""Supplement owner-only /durum with facts from authoritative archived ledger.

No platform API or writable action. All counts are historical, not live.
"""
from collections import Counter
from html import escape
from publication_operations import series_report


def status_evidence(state):
    if not isinstance(state, dict) or not isinstance(state.get("entries"), dict):
        return "\n<b>Yayın geçmişi:</b> N/A (doğrulanmış arşiv okunamadı)."
    rows = [r for r in state["entries"].values() if isinstance(r, dict)]
    done = [r for r in rows if r.get("status") == "done" and r.get("post_id")]
    pending = [r for r in rows if r.get("status") in {"uncertain", "intent", "held"}]
    ready_failed = [r for r in rows if r.get("status") == "ready" and r.get("failure")]
    recent = sorted(done, key=lambda r: str(r.get("day") or ""), reverse=True)[:5]
    lines = [
        "<b>Arşiv özeti</b>",
        f"Kimliği kayıtlı toplam yayın: {len({(r.get('route'),r.get('platform'),str(r['post_id'])) for r in done})}",
        f"Belirsiz/bekleyen kayıt: {len(pending)}; hazırlık hatası: {len(ready_failed)}",
        "<b>Son arşivlenmiş yayınlar</b>"
    ]
    if recent:
        for r in recent:
            lines.append(escape(f"{r.get('day','?')} {r.get('route','?')}/{r.get('platform','?')}: {r['post_id']}"))
    else:
        lines.append("N/A")
    if pending:
        counts = Counter((r.get("route"),r.get("platform")) for r in pending)
        lines.append("<b>Uzlaştırılmamış kayıtlar</b>")
        lines += [escape(f"{route}/{platform}: {count}") for (route, platform), count in sorted(counts.items(),key=lambda x:str(x[0]))]
    try:
        observations = series_report(state)["series"]
        problems = [r for r in observations if r["missing_parts"] or r["conflicting_parts"]]
        lines.append("<b>Seri/bölüm gözlemi</b>")
        if not problems:
            lines.append("Gözlenen arşivde açık bulunmadı; kaynak stoğu ayrıca kontrol edilmeli.")
        for item in problems[:8]:
            lines.append(escape(f"{item['route']}/{item['platform']} {item['series'][:25]}: eksik {item['missing_parts'][:12]}, çakışan {item['conflicting_parts'][:12]}"))
        if len(problems) > 8:
            lines.append(f"... {len(problems)-8} ek seri sorunu")
    except (ValueError, TypeError, KeyError):
        lines.append("Seri/bölüm kanıtı: N/A")
    lines.append("Stok, token/kota ve son otomasyon zamanı: Bu arşivde yok (N/A).")
    lines.append("Bu geçmiş doğrulamasıdır; güncel platform GET sonucu değildir.")
    return "\n" + "\n".join(lines)
