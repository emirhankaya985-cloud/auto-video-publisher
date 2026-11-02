"""Bounded Meta report tables for Telegram HTML and ntfy plain text."""
from html import escape


def publication_rows(data):
    result = []
    progress = data.get('publication', {})
    for i, account in enumerate(data['accounts'], 1):
        p = progress.get(account['account'])
        if p is None:
            result.append([str(i), 'N/A', 'N/A', 'N/A'])
            continue
        success = sum(v['success'] for v in p['platforms'].values())
        missing = sum(max(p['target'] - v['success'], 0) for v in p['platforms'].values())
        result.append([str(i), str(success), str(p['expected_posts']), str(missing)])
    return result


def plain_table(headers, rows):
    widths = [max(len(str(row[i])) for row in [headers] + rows) for i in range(len(headers))]
    return '\n'.join(' | '.join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))
                     for row in [headers] + rows)


def publication_telegram(data):
    table = plain_table(['Hesap', 'Yayin', 'Hedef', 'Eksik'], publication_rows(data))
    legend = '\n'.join(f"{i}. {escape(a['account'])}" for i, a in enumerate(data['accounts'], 1))
    return ('📋 Meta yayın tablosu', f"<b>Gün:</b> {escape(data['day'])}\n<pre>{escape(table)}</pre>\n{legend}\n"
            'Sayılar platform gönderisidir (FB + IG). Belirsiz kayıtlar başarı sayılmaz.')


def ntfy_table(data):
    def number(v):
        return 'N/A' if v is None else f'{v:,}'.replace(',', '.')
    rows = []
    pub = publication_rows(data)
    for i, a in enumerate(data['accounts']):
        delta = a['daily']['delta']
        rows.append(pub[i] + [('+' if delta is not None else '') + number(delta), number(a['total'])])
    text = (f"META RAPORU — {data['day']}\nÖlçüm: {data['measured_at']}\n\n"
            + plain_table(['Hesap', 'Yayin', 'Hedef', 'Eksik', '1g artis', 'Toplam'], rows)
            + '\n\n' + '\n'.join(f"{i}. {a['account']}" for i,a in enumerate(data['accounts'],1))
            + f"\n\nToplam izlenme: {number(data['total'])}\nGünlük artış: {number(data['daily']['delta'])}"
            + '\nYayın = FB + IG platform gönderisi. Belirsizler başarı sayılmaz. N/A = veri yok.'
            + '\nİzlenmeler erişilebilir video sayaçlarıdır; tekil izleyici değildir.')
    if data.get('collection_errors'):
        text += '\n⚠️ Eksik veri / erişim hatası var; ayrıntılar Actions raporunda.'
    if len(text.encode('utf-8')) > 3800:
        raise ValueError('Meta ntfy table exceeds message limit')
    return text
