"""Side-effect-free ordered ToonZone slots for the shared GitHub publisher."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TRT = ZoneInfo("Europe/Istanbul")
TOONZONE_HOUR = 12
TOONZONE_PART_MINUTES = (0, 10, 20, 30)


def due_toonzone_slots(now, earliest, *, enabled):
    """Return only due ordered slots; never create a slot for a disabled route.

    Catch up delayed ticks on the current Istanbul calendar day only; do not
    replay an older day's ToonZone episode the next morning. Only timestamps
    in [earliest, now] are eligible. No Drive or Meta API call is made.
    """
    if not enabled:
        return []
    now = now.astimezone(TRT)
    earliest = earliest.astimezone(TRT)
    result = []
    for day in (now.date(),):
        for part, minute in enumerate(TOONZONE_PART_MINUTES, start=1):
            planned = datetime(day.year, day.month, day.day, TOONZONE_HOUR, minute, tzinfo=TRT)
            if earliest <= planned <= now:
                result.append((planned, "toonzone", f"{day:%Y-%m-%d}-12-toonzone-part{part}"))
    return result


def toonzone_part_eligible(slot, ordered, *, used_key, last_slot_key):
    """Only the next unfinished part may occupy its matching current-day slot.

    Never restart a new episode's Part 1 after a later part was already posted
    today. This is read-only and does not excuse any existing claim or intent.
    """
    import re
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})-12-toonzone-part([1-4])", slot)
    if not match:
        raise ValueError("Invalid ToonZone scheduled slot")
    day, slot_part = match.group(1), int(match.group(2))
    next_row = next(
        (row for row in ordered if (row[2].get("appProperties") or {}).get(used_key) != "1"),
        None,
    )
    if next_row is None or next_row[0][2] != slot_part:
        return False
    for _order, _stem, video, _text in ordered:
        props = video.get("appProperties") or {}
        if props.get(used_key) != "1":
            continue
        recorded = str(props.get(last_slot_key) or "")
        scheduled = re.fullmatch(rf"{re.escape(day)}-12-toonzone-part([1-4])", recorded)
        manual = re.fullmatch(rf"manual-{re.escape(day)}-\d{{4}}-toonzone-toonzone-part([1-4])", recorded)
        sent_part = scheduled or manual
        if sent_part and int(sent_part.group(1)) > slot_part:
            return False
    return True
