"""Pure account comparisons and bounded Telegram HTML tables; no network calls."""
import html
import json
from datetime import datetime, timedelta
from pathlib import Path


class ViewReport(str):
    def __new__(cls, text, comparison):
        obj = super().__new__(cls, text)
        obj.comparison = comparison
        return obj


def number(value):
    return "N/A" if value is None else f"{value:,}".replace(",", ".")


def percentage(value):
    if value is None:
        return "N/A"
    precision = 4 if 0 < abs(value) < 0.1 else 2
    return f"{value:+.{precision}f}%".replace(".", ",")


def _stamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except (ValueError, TypeError, AttributeError):
        return None


def _count(value):
    # Refuse bools, negative counters, fractions and malformed archived values.
    if type(value) is int and value >= 0:
        return value
    return None


def load_history(path):
    if not Path(path).exists():
        return []
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _baseline(history, account, platform, day, current):
    rows = [r for r in history if r.get("account") == account
            and r.get("platform") == platform and r.get("period") == day]
    status = next((r for r in reversed(rows) if r.get("entity_type") == "account"
                   and r.get("metric") == "snapshot_status"), None)
    total = next((r for r in reversed(rows) if r.get("entity_type") == "account"
                  and r.get("metric") == "lifetime_views"), None)
    if not status or not total:
        return None, "geçmiş yok"
    if status.get("status") != "ok" or total.get("status") != "ok":
        return None, "geçmiş ölçüm hatalı"
    videos = {str(r.get("entity_id")): r for r in rows
              if r.get("entity_type") == "video" and r.get("metric") == "view_count"}
    values = [_count(r.get("value")) if r.get("status") == "ok" else None
              for r in videos.values()]
    value = _count(total.get("value"))
    if (_count(status.get("value")) != len(videos) or value is None
            or any(v is None for v in values) or sum(values) != value):
        return None, "geçmiş eksik"
    if current is None or set(videos) - set(current):
        return None, "video kapsamı değişti"
    for video_id, old in videos.items():
        if _count(current[video_id].get("views")) is None or current[video_id]["views"] < old["value"]:
            return None, "sayaç düzeltmesi"
    measured = _stamp(status.get("measured_at"))
    for video_id in set(current) - set(videos):
        published = _stamp(current[video_id].get("published_at"))
        if measured is None or published is None or published <= measured:
            return None, "eski video sonradan erişilebilir"
    return value, "ok"


def build_comparison(snapshot, history, accounts, report_day, measured_at, *, delayed=False):
    """Percentages compare accessible cumulative video totals on exact dates.

    Never substitute another date for a missing seven-day baseline, silently
    compare different platform sets, or turn a missing API result into zero.
    """
    day = report_day.isoformat()
    dates = {"daily": (report_day - timedelta(days=1)).isoformat(),
             "weekly": (report_day - timedelta(days=7)).isoformat()}
    valid_days = sorted({r.get("period") for r in history
                         if isinstance(r.get("period"), str) and len(r["period"]) == 10})
    result = {"day": day, "measured_at": measured_at, "baseline_dates": dates,
              "archive_first_day": valid_days[0] if valid_days else None, "accounts": []}
    for account, platforms in accounts.items():
        row = {"account": account, "platforms": [], "total": None, "videos": None}
        for platform in sorted(platforms):
            current = snapshot.get((account, platform))
            valid = isinstance(current, dict) and all(_count(v.get("views")) is not None for v in current.values())
            part = {"platform": platform,
                    "total": sum(v["views"] for v in current.values()) if valid else None,
                    "videos": len(current) if valid else None}
            for period, date in dates.items():
                old, reason = _baseline(history, account, platform, date, current) if valid else (None, "API verisi yok")
                if delayed:
                    old, reason = None, "gecikmeli ölçüm"
                delta = part["total"] - old if old is not None else None
                part[period] = {"baseline": old, "delta": delta,
                                "percent": (delta / old * 100) if old else None,
                                "reason": "taban sıfır" if old == 0 else reason}
            row["platforms"].append(part)
        complete = bool(row["platforms"]) and all(p["total"] is not None for p in row["platforms"])
        if complete:
            row["total"] = sum(p["total"] for p in row["platforms"])
            row["videos"] = sum(p["videos"] for p in row["platforms"])
        for period in dates:
            parts = [p[period] for p in row["platforms"]]
            comparable = complete and all(p["baseline"] is not None for p in parts)
            old = sum(p["baseline"] for p in parts) if comparable else None
            delta = row["total"] - old if comparable else None
            row[period] = {"baseline": old, "delta": delta,
                           "percent": delta / old * 100 if old else None,
                           "reason": ", ".join(sorted({p["reason"] for p in parts if p["reason"] != "ok"})) or "ok"}
        result["accounts"].append(row)
    rows = result["accounts"]
    result["total"] = sum(r["total"] for r in rows) if rows and all(r["total"] is not None for r in rows) else None
    for period in dates:
        complete = result["total"] is not None and all(r[period]["baseline"] is not None for r in rows)
        old = sum(r[period]["baseline"] for r in rows) if complete else None
        delta = result["total"] - old if complete else None
        result[period] = {"baseline": old, "delta": delta,
                          "percent": delta / old * 100 if old else None}
    return result


def _table(headers, rows):
    cells = [list(map(str, headers))] + [list(map(str, r)) for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(headers))]
    lines = ["  ".join(value.ljust(widths[i]) if i == 0 else value.rjust(widths[i])
                       for i, value in enumerate(row)) for row in cells]
    return "<pre>" + html.escape("\n".join(lines)) + "</pre>"


def telegram_tables(data):
    rows = data["accounts"]
    legend = "\n".join(f"{i}. {html.escape(r['account'])}" for i, r in enumerate(rows, 1))
    first = (f"<b>Ölçüm:</b> {html.escape(data['measured_at'])}\n"
             f"<b>Gün:</b> {data['day']} | <b>Taban:</b> {data['baseline_dates']['daily']}\n\n"
             + _table(["Hesap", "Dün", "Şimdi", "1g artış", "1g %"], [
                 [i, number(r["daily"]["baseline"]), number(r["total"]), ("+" + number(r["daily"]["delta"])) if r["daily"]["delta"] is not None else "N/A",
                  percentage(r["daily"]["percent"])] for i, r in enumerate(rows, 1)])
             + "\n" + legend + "\n\n<b>Genel toplam:</b> " + number(data["total"])
             + "\n<b>Toplam günlük artış:</b> " + number(data["daily"]["delta"]) + " (" + percentage(data["daily"]["percent"]) + ")"
             + "\nYüzde = toplam video sayacının taban tarihe göre büyümesi; günlük izlenme hızının yüzdesi değildir.")
    daily_missing = [f"{i}: {html.escape(r['daily']['reason'])}" for i, r in enumerate(rows, 1)
                     if r["daily"]["baseline"] is None]
    if daily_missing:
        first += "\n\n<b>Günlük veri durumu:</b>\n" + "\n".join(daily_missing)
    second = (f"<b>7 gün önceki taban:</b> {data['baseline_dates']['weekly']}\n\n"
              + _table(["Hesap", "7g önce", "7g artış", "7g %"], [
                  [i, number(r["weekly"]["baseline"]),
                   ("+" + number(r["weekly"]["delta"])) if r["weekly"]["delta"] is not None else "N/A",
                   percentage(r["weekly"]["percent"])] for i, r in enumerate(rows, 1)]))
    unavailable = [f"{i}: {html.escape(r['weekly']['reason'])}" for i, r in enumerate(rows, 1)
                   if r["weekly"]["baseline"] is None]
    second += "\n" + legend
    second += "\n\n<b>Toplam 7g artış:</b> " + number(data["weekly"]["delta"]) + " (" + percentage(data["weekly"]["percent"]) + ")"
    if unavailable:
        second += "\n\n<b>Haftalık veri durumu:</b>\n" + "\n".join(unavailable)
    second += "\nArşivde ilk tarih: " + (data.get("archive_first_day") or "N/A")
    leaders = sorted((r for r in rows if r["daily"]["delta"] is not None),
                     key=lambda r: r["daily"]["delta"], reverse=True)
    third = ["<b>Günlük artış liderleri</b>"]
    for i, row in enumerate(leaders[:3], 1):
        third.append(f"{i}. {html.escape(row['account'])}: +{number(row['daily']['delta'])} ({percentage(row['daily']['percent'])})")
    if not leaders:
        third.append("Karşılaştırılabilir günlük veri yok.")
    third.append("\n<b>Platform ayrıntısı · toplam / 1g % / 7g %</b>")
    for row in rows:
        share = f"{row['total'] / data['total'] * 100:.2f}%".replace(".", ",") if data["total"] and row["total"] is not None else "N/A"
        third.append(f"\n<b>{html.escape(row['account'])}</b> · Toplamdaki pay: {share}"
                     f" · Video kaydı: {number(row['videos'])}")
        for part in row["platforms"]:
            third.append(f"{html.escape(part['platform'])}: {number(part['total'])} / {percentage(part['daily']['percent'])} / {percentage(part['weekly']['percent'])}")
    third.append("\nN/A: taban eksik, API/kapsam sorunu veya taban sıfır. Sıfırdan büyüme sonsuz yüzde gösterilmez."
                 "\nKapsam: erişilebilir video sayaçları; tekil izleyici değildir. Manuel rapor günün tamamı değildir.")
    messages = [("📊 Hesap tablosu · 1/3", first), ("📅 Haftalık karşılaştırma · 2/3", second),
                ("🏆 Performans ve platformlar · 3/3", "\n".join(third))]
    if any(len((title + body).encode("utf-16-le")) // 2 > 3800 for title, body in messages):
        raise ValueError("Detailed Telegram report exceeds bounded message size")
    return messages
