"""Independent, durable notification intents and incident correlation.

Video publication state is never edited. Intents precede notification sends;
results record server ACKs, not phone delivery. Reads fail closed on corrupt
history, preventing an accidental reset and a burst of duplicate alerts.
"""
import hashlib
import io
import json
import os
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from publisher_recovery import read_with_retry

REPO = 'emirhankaya985-cloud/auto-video-publisher'
HISTORY = Path('link-runtime/alert-history.json')
PREPARED = Path('link-runtime/notifications.json')
NAMES = ('link-alert-intent', 'link-alert-result')


def now_utc():
    return datetime.now(timezone.utc)


def stamp(value):
    try:
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        if dt.tzinfo is None: raise ValueError()
        return dt.astimezone(timezone.utc)
    except (TypeError,ValueError,AttributeError):
        raise ValueError('invalid alert timestamp') from None


def save(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def validate(history):
    if not isinstance(history,dict) or history.get('schema')!=1 or not isinstance(history.get('records'),dict):
        raise ValueError('invalid alert history')
    if len(history['records'])>10000: raise ValueError('alert history limit')
    for key,row in history['records'].items():
        if not isinstance(key,str) or len(key)!=64 or not isinstance(row,dict):
            raise ValueError('invalid alert record')
        stamp(row['last_seen'])
        if row.get('last_intent'): stamp(row['last_intent'])
        for field in ('server_acks','attempted_channels'):
            values=row.get(field,[])
            if not isinstance(values,list) or any(v not in {'telegram','ntfy'} for v in values):
                raise ValueError('invalid notification receipt')
        if not isinstance(row.get('observed_runs',[]),list):
            raise ValueError('invalid incident runs')
    return history


def restore(*, get=None):
    get=get or requests.get
    token=os.getenv('GH_TOKEN') or os.getenv('GITHUB_TOKEN')
    if not token: raise ValueError('alert archive token missing')
    headers={'Authorization':f'Bearer {token}'}
    def fetch(path, archive=False):
        r=read_with_retry(get,f'https://api.github.com/repos/{REPO}/{path}',headers=headers,
                          timeout=30,allow_redirects=archive)
        if r.status_code!=200: raise ValueError('alert archive unavailable')
        return r
    try:
        candidates=[]
        for name in NAMES:
            body=fetch(f'actions/artifacts?per_page=100&name={name}').json()
            if not isinstance(body,dict) or not isinstance(body.get('artifacts'),list):
                raise ValueError('invalid alert artifact list')
            candidates.extend(body['artifacts'])
        if not candidates: return {'schema':1,'records':{}}
        candidates.sort(key=lambda a:(int(a['workflow_run']['id']),a['name']==NAMES[1]),reverse=True)
        a=candidates[0]
        run=fetch(f"actions/runs/{a['workflow_run']['id']}").json()
        if (a.get('expired') or run.get('head_branch')!='main'
                or run.get('head_repository',{}).get('full_name')!=REPO
                or run.get('path')!='.github/workflows/public_link_schedule.yml'):
            raise ValueError('unverified alert archive origin')
        response=fetch(f"actions/artifacts/{a['id']}/zip",archive=True)
        if len(response.content)>8_000_000: raise ValueError('alert archive too large')
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            if z.namelist()!=['alert-history.json'] or z.getinfo('alert-history.json').file_size>8_000_000:
                raise ValueError('invalid alert archive')
            return validate(json.loads(z.read('alert-history.json')))
    except Exception:
        raise ValueError('alert archive restore failed; reset forbidden') from None


def identity(kind, route='', platform='', video='', extra=''):
    return hashlib.sha256(json.dumps([kind,route,platform,video,extra],ensure_ascii=False).encode()).hexdigest()


def incident_descriptors(events):
    result={}
    for e in events:
        route,platform,video=(str(e.get(k) or '') for k in ('route','platform','video'))
        reason=e.get('reason','')
        family=('media' if reason in {'invalid_media_or_graph_request','unreconciled_previous_intent'}
                else 'source' if e.get('stage') in {'source_video','drive_inventory','txt_caption','toonzone_cover'}
                else str(reason))
        key=identity('incident',route,platform,video,family)
        result[key]={'kind':'incident','route':route,'platform':platform,'video':video,'family':family}
    return result


def observe(history, descriptors, state, run_id, *, now):
    validate(history)
    # Resolve only against actual done post IDs, never workflow success.
    entries=state.get('entries',{})
    for row in history['records'].values():
        if row.get('kind')!='incident': continue
        for e in entries.values():
            if (isinstance(e,dict) and e.get('status')=='done' and e.get('post_id')
                    and (str(e.get('run_id'))==run_id or str(e.get('reconciled_in_run_id'))==run_id)
                    and e.get('route')==row.get('route') and e.get('file')==row.get('video')
                    and (e.get('platform')==row.get('platform') or row.get('family')=='source')):
                row['resolved']=True
                break
    for key,descriptor in descriptors.items():
        row=history['records'].setdefault(key,dict(descriptor,server_acks=[],resolved=False))
        if row.get('resolved'):
            row.pop('last_intent',None)
        row.update(last_seen=now.isoformat(),resolved=False)
        seen=row.setdefault('observed_runs',[])
        if run_id not in seen: seen.append(run_id)
        row['observed_runs']=seen[-48:]


def reserve(history, title, body, descriptors, run_id, *, now):
    """Return one durable message intent or None for an unchanged incident."""
    records=history['records']
    keys=list(descriptors)
    if not keys: raise ValueError('notification identity missing')
    fresh=any(not records.get(k,{}).get('last_intent') for k in keys)
    is_post=all(d['kind']=='post' for d in descriptors.values())
    due=fresh or (not is_post and any(now-stamp(records[k]['last_intent'])>=timedelta(hours=24) for k in keys))
    if not due: return None
    if not fresh and not is_post:
        title='ℹ️ Yayın engeli devam ediyor'
        body='ℹ️ Önceden bildirilen olayın günlük hatırlatması.\n'+body
    for k,d in descriptors.items():
        row=records.setdefault(k,dict(d,last_seen=now.isoformat(),observed_runs=[run_id],resolved=False))
        row.update(last_intent=now.isoformat(),intent_run_id=run_id,server_acks=[],attempted_channels=[])
    return {'title':title,'body':body,'keys':keys}


def mark_ack(history, message, channel):
    if channel not in {'telegram','ntfy'}: raise ValueError('unknown channel')
    for k in message['keys']:
        acks=history['records'][k].setdefault('server_acks',[])
        if channel not in acks: acks.append(channel)


def covered(history, *, run_ids=None, route=None, platforms=None, now=None):
    """Only ACKed, unresolved, recent incident records cover another alarm."""
    now=now or now_utc()
    rows=[r for r in validate(history)['records'].values()
          if r.get('kind')=='incident' and not r.get('resolved') and r.get('server_acks')
          and now-timedelta(hours=6)<=stamp(r['last_seen'])<=now]
    if run_ids:
        return all(any(str(rid) in r.get('observed_runs',[]) for r in rows) for rid in run_ids)
    if route and platforms:
        return all(any(r.get('route')==route and (r.get('platform')==p or r.get('family')=='source')
                       for r in rows) for p in platforms)
    return False
