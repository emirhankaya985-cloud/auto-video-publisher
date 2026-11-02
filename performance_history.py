"""Optional GET-only engagement snapshots using the canonical daily archive."""
from analytics_archive import make_record


def counter(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def follower_changes(records, previous):
    result = []
    for row in records:
        if row['metric'] != 'followers':
            continue
        key = (row['account'], row['platform'], row['entity_type'], row['entity_id'], row['metric'])
        prior = previous.get(key, {})
        current = counter(row['value']) if row['status'] == 'ok' else None
        old = counter(prior.get('value')) if prior.get('status') == 'ok' else None
        result.append(dict(account=row['account'], platform=row['platform'],
                           followers=current, daily_change=current - old
                           if current is not None and old is not None else None))
    return result


def collect_engagement(targets, get_page, graph_get, graph_pages, *, measured_at, period):
    records, errors = [], []
    def add(account, platform, entity, entity_id, metric, value, source):
        value = counter(value)
        records.append(make_record(measured_at=measured_at, timezone='Europe/Istanbul',
            account=account, platform=platform, entity_type=entity, entity_id=entity_id,
            metric=metric, value=value, period=period, unit='count',
            source_api='meta.graph', source_metric=source,
            status='ok' if value is not None else 'unavailable'))
    for account, page_name, platform in targets:
        try:
            page = get_page(page_name)
            token = page['page_token']
            object_id = page['page_id'] if platform.startswith('Facebook') else page['instagram_id']
        except Exception:
            errors.append(f'{account} / {platform}: engagement account unavailable')
            add(account, platform, 'account', account, 'followers', None, 'followers_count')
            continue
        try:
            data = graph_get(object_id, token, fields='id,followers_count')
            if str(data.get('id')) != str(object_id):
                raise ValueError('account mismatch')
            add(account, platform, 'account', account, 'followers', data.get('followers_count'), 'followers_count')
        except Exception:
            errors.append(f'{account} / {platform}: followers unavailable')
            add(account, platform, 'account', account, 'followers', None, 'followers_count')
        video_start = len(records)
        try:
            facebook = platform.startswith('Facebook')
            edge = 'videos' if facebook else 'media'
            fields = ('id,likes.limit(0).summary(true),comments.limit(0).summary(true)'
                      if facebook else 'id,media_type,like_count,comments_count')
            # Buffer the whole paginated result: a late failure must not present
            # partial engagement coverage as a complete daily measurement.
            videos = list(graph_pages(f'{object_id}/{edge}', token, fields=fields, limit=100))
            seen = set()
            for video in videos:
                if not facebook and video.get('media_type') != 'VIDEO':
                    continue
                vid = str(video.get('id') or '')
                if not vid.isdecimal():
                    raise ValueError('invalid video id')
                if vid in seen:
                    continue
                seen.add(vid)
                for metric, field in (('like_count', 'likes'), ('comment_count', 'comments')):
                    if facebook:
                        value = ((video.get(field) or {}).get('summary') or {}).get('total_count')
                    else:
                        value = video.get('like_count' if field == 'likes' else 'comments_count')
                    add(account, platform, 'video', vid, metric, value, fields)
        except Exception:
            del records[video_start:]
            errors.append(f'{account} / {platform}: video engagement unavailable')
    return records, errors
