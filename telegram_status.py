"""Read-only status and publication timetable for the existing report chat."""
import json
import os
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram_status_evidence import status_evidence
from owner_daily_quota import POST_ID
from adaptive_schedule import slots_for_route
from publication_github_progress import restore_publication_state
from publication_safety import route_paused
from scheduled_multi_publisher import (TARLADAKI_HOURS, PENGUEN_HOURS, GONLE_HOURS,
                                       FILM_HOURS, daily_laugh_hours_for_date)

TR = ZoneInfo('Europe/Istanbul')
NAMES = {'tarladaki': 'Fasulye', 'penguen': 'Penguen', 'gonle': 'Gönle Düşen',
         'daily_laugh': 'Daily Laugh', 'film': 'Film Mağarası',
         'film_second': 'Film FB 2', 'toonzone': 'ToonZone',
         'oddframes': 'OddFrames'}
FLAGS = ('LINK_AUTOMATION_ENABLED', 'ADAPTIVE_SCHEDULE_ENABLED',
         'ENABLE_TP_NORMAL_ROUTES', 'ENABLE_GONLE_NORMAL_ROUTES',
         'ENABLE_GONLE_INSTAGRAM_ROUTES', 'ENABLE_DAILY_LAUGH_NORMAL_ROUTES',
         'ENABLE_DAILY_LAUGH_INSTAGRAM_ROUTES', 'ENABLE_FILM_ROUTES',
         'FILM_RIGHTS_APPROVED', 'ENABLE_TOONZONE_ROUTES',
         'ENABLE_NEW_META_ROUTES', 'META_NEW_ROUTES_RIGHTS_APPROVED')


def status_table(*, now=None, state=None, configured=False):
    now = now or datetime.now(TR)
    if now.tzinfo is None:
        raise ValueError('aware report time required')
    now = now.astimezone(TR)
    entries = state.get('entries', {}) if state is not None else None
    policy = (state or {}).get('adaptive_schedule_days', {}).get(now.date().isoformat(), {})
    lines = ['Hesap          FB     IG    Gec Bek Hata Ayar', '---------------------------------------------']
    hours = ['Hesap          Saatler (TR)', '--------------------------------']
    for route, name in NAMES.items():
        if route == 'oddframes':
            # Never infer a target/identity from another owner's Meta page.
            # Its own preflight must pass before a real schedule can be added.
            lines.append(f'{name:<14} {"N/A":<6} {"N/A":<5} {"-":>3} {"-":>3} {"-":>4} Kapalı')
            hours.append(f'{name:<14} Kimlik/hak bekleniyor')
            continue
        clock = now.astimezone(ZoneInfo('America/New_York')) if route == 'daily_laugh' else now
        if route == 'toonzone':
            slots = [(12, m) for m in (0, 10, 20, 30)]
        else:
            base = (daily_laugh_hours_for_date(clock.date()) if route == 'daily_laugh' else
                    {'tarladaki': TARLADAKI_HOURS, 'penguen': PENGUEN_HOURS,
                     'gonle': GONLE_HOURS, 'film': FILM_HOURS,
                     'film_second': FILM_HOURS}[route])
            minute = 30 if route == 'penguen' else 15 if route == 'gonle' else 0
            slots = [(h, minute) for h in base]
        if os.getenv('ADAPTIVE_SCHEDULE_ENABLED', 'true') != 'false':
            slots = slots_for_route(policy, route, now, slots)
        target = len(slots)
        report_day = (clock.date() - timedelta(days=1)
                      if route == 'daily_laugh' else clock.date()).isoformat()
        # A same-day full target gap is NOT a missed deadline before slots.
        # Daily Laugh reports the previous fully completed New York day.
        due_slots = (target if report_day < clock.date().isoformat() else
                     sum(clock >= clock.replace(hour=h, minute=m, second=0, microsecond=0)
                         for h, m in slots))
        overdue_total, pending_total, local_failed_total = 0, 0, 0
        counts = []
        for platform in ('facebook', 'instagram'):
            if route == 'film_second' and platform == 'instagram':
                counts.append('—')
            elif configured and platform == 'instagram' and (
                    (route == 'gonle' and route_paused('gonle_ig')) or
                    (route == 'daily_laugh' and route_paused('daily_laugh_instagram'))):
                counts.append('Kapalı')
            elif entries is None:
                counts.append('N/A')
            else:
                selected = [r for r in entries.values()
                            if isinstance(r, dict) and r.get('route') == route
                            and r.get('platform') == platform and r.get('day') == report_day]
                posts = {str(r.get('post_id')) for r in selected
                         if r.get('status') == 'done' and POST_ID.fullmatch(str(r.get('post_id') or ''))}
                overdue_total += max(0, due_slots - len(posts))
                pending_total += sum(r.get('status') in ('intent', 'uncertain', 'held', 'pending')
                                     for r in selected)
                local_failed_total += sum(r.get('status') == 'ready'
                                          and isinstance(r.get('failure'), dict)
                                          for r in selected)
                counts.append(f'{len(posts)}/{target}')
        setting = 'N/A'
        if configured:
            enabled = os.getenv('LINK_AUTOMATION_ENABLED') == 'true' and not route_paused('film' if route == 'film_second' else route)
            setting = 'Açık' if enabled else 'Kapalı'
        gap = str(overdue_total) if entries is not None else 'N/A'
        wait = str(pending_total) if entries is not None else 'N/A'
        fail = str(local_failed_total) if entries is not None else 'N/A'
        lines.append(f'{name:<14} {counts[0]:<6} {counts[1]:<5} {gap:>3} {wait:>3} {fail:>4} {setting}')
        times = []
        for h, m in slots:
            stamp = clock.replace(hour=h, minute=m, second=0, microsecond=0).astimezone(TR)
            times.append(stamp.strftime('%H:%M') + ('(+1)' if stamp.date() > now.date() else '(-1)' if stamp.date() < now.date() else ''))
        # Daily Laugh has eight slots: wrap instead of a very wide phone row.
        for start in range(0, len(times), 4):
            hours.append(f'{name if start == 0 else "":<14} ' + ' '.join(times[start:start+4]))
    return (f'<b>Yayın durumu — {now:%d.%m.%Y %H:%M} TR</b>\n'
            '<pre>' + escape('\n'.join(lines)) + '</pre>\n'
            '<b>Tanımlı yayın planı</b>\n<pre>' + escape('\n'.join(hours)) + '</pre>\n'
            'FB/IG: arşivde ID kayıtlı / günlük hedef. Gec: zamanı geçmiş slotların kayıtsız açığı; Bek: belirsiz veya bekletilen; Hata: yerel hazırlık. N/A: doğrulanamıyor.\n'
            'OddFrames: geçerli kimlik/hak verisi sağlanmadı, kota ve yayın sayısı N/A. '+
            'Saatler planı gösterir; hak, kaynak, kota ve tekrar kontrolleri yayını bekletebilir. '
            'Daily Laugh sayıları son tamamlanmış New York gününe, saatleri güncel NY planına aittir; saatler TR’ye çevrildi. '
            '(+1)/(-1): rapor tarihine göre ertesi/önceki gün.\n'
            'Gönderi sayıları son arşivden gelir; bu bilgi canlı anlık izlenme değildir.' + status_evidence(state))


def load_status():
    try:
        state = restore_publication_state()
    except RuntimeError:
        state = None
    return status_table(state=state)


def main():
    import argparse
    from telegram_notifications import send_telegram
    parser = argparse.ArgumentParser()
    parser.add_argument('--send', action='store_true')
    args = parser.parse_args()
    configured = False
    if os.getenv('PUBLISHER_VARS_JSON'):
        variables = json.loads(os.environ['PUBLISHER_VARS_JSON'])
        if not isinstance(variables, dict):
            raise RuntimeError('publisher_settings_unavailable')
        for flag in FLAGS:
            os.environ[flag] = str(variables.get(flag, ''))
        configured = True
    try:
        state = restore_publication_state()
    except RuntimeError:
        state = None
    message = status_table(state=state, configured=configured)
    root = Path('link-runtime'); root.mkdir(exist_ok=True)
    (root / 'telegram-status.html').write_text(message, encoding='utf-8')
    if args.send:
        receipt = send_telegram('📋 Yayın planlaması', message, parse_mode='HTML')
        (root / 'telegram-status-receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
        print(json.dumps({'server_ack': receipt['server_ack'], 'phone_delivery_verified': False}))


if __name__ == '__main__':
    main()
