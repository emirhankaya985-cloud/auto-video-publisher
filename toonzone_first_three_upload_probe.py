"""Upload-only probe for the failed first part; never calls media_publish."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import toonzone_instagram_first_three as batch
import publisher_alert_history as archive

ROOT=Path('toonzone-first-three-upload-probe')
HISTORY=ROOT/'alert-history.json'
WORKFLOW='.github/workflows/toonzone_first_three_upload_probe.yml'
NAMES=('toonzone-first-three-upload-probe-intent','toonzone-first-three-upload-probe-result')


def prepare():
    from public_link_runtime import download,download_verified_publication_video
    from cloud_omnichannel_publisher import create_instagram_cover_video
    from instagram_media_compat import prepare_instagram_upload
    page=batch.page_for_toonzone()
    if batch.instagram_identity(page)!=batch.EXPECTED_INSTAGRAM_ID: raise RuntimeError('wrong_account')
    history=archive.restore(names=batch.NAMES,workflow_path=batch.WORKFLOW)
    rows=[r for r in history['records'].values() if r.get('file')=='S01E01_The_Power_Part1.mp4']
    if len(rows)!=1: raise RuntimeError('first_part_evidence_missing')
    prior=rows[0]
    if prior.get('status')!='attempted' or prior.get('diagnostic',{}).get('container_id')!='17911372950580142': raise RuntimeError('unexpected_previous_attempt')
    # This stopped run's logs prove media_publish was never entered. Preserve its
    # container and byte identities; this probe is explicitly upload-only.
    if prior.get('post_id'): raise RuntimeError('first_part_already_published')
    ROOT.mkdir(exist_ok=True)
    cover=download(prior['cover_id'],ROOT/'cover.png')
    if batch.digest(cover)!=prior['cover_sha256']: raise RuntimeError('cover_changed')
    source=download_verified_publication_video(prior['source_id'],ROOT/'source.mp4')
    if batch.digest(source)!=prior['source_sha256']: raise RuntimeError('source_changed')
    covered=create_instagram_cover_video(source,cover,ROOT/'covered.mp4',preserve_full_cover=True)
    video=prepare_instagram_upload(covered,ROOT/'instagram.mp4',toonzone_compact=True)
    frame=ROOT/'prepared.jpg'
    subprocess.run(['ffmpeg','-y','-i',str(video),'-frames:v','1',str(frame)],check=True,capture_output=True,timeout=60)
    if batch.cover_distance(cover,frame)>0.12: raise RuntimeError('cover_mismatch')
    record=dict(prior,status='reserved',intent_run_id=os.environ['GITHUB_RUN_ID'],last_seen=archive.now_utc().isoformat(),
                previous_container_id='17911372950580142',candidate_upload_sha256=batch.digest(video),
                candidate_upload_bytes=video.stat().st_size,candidate_profile='toonzone_compact',publish_allowed=False)
    archive.save(HISTORY,{'schema':1,'records':{'0'*64:record}})
    print('UPLOAD_ONLY_PROBE_RESERVED bytes='+str(video.stat().st_size),flush=True)


def upload():
    from cloud_omnichannel_publisher import upload_instagram_reel,MetaAPIError
    if os.getenv('UPLOAD_PROBE_INTENT_ARCHIVED')!='true': raise RuntimeError('probe_not_archived')
    history=archive.validate(archive.read(HISTORY));record=history['records']['0'*64]
    video=ROOT/'instagram.mp4'
    if record['status']!='reserved' or record['intent_run_id']!=os.environ['GITHUB_RUN_ID'] or batch.digest(video)!=record['candidate_upload_sha256']: raise RuntimeError('probe_changed')
    page=batch.page_for_toonzone()
    if batch.instagram_identity(page)!=batch.EXPECTED_INSTAGRAM_ID: raise RuntimeError('wrong_account')
    record['status']='attempted';archive.save(HISTORY,history)
    try:
        result=upload_instagram_reel(page,str(video),record['caption'],append_store_link=False,publish=False,thumb_offset=0,forbidden_container_ids={'17911372950580142'})
        record.update(status='finished_upload_only',candidate_container_id=result['container_id'])
        print('UPLOAD_ONLY_PROBE_FINISHED '+json.dumps(result),flush=True)
    except MetaAPIError as exc:
        record.update(status='upload_failed',error=str(exc),candidate_container_id=getattr(exc,'container_id',None),candidate_status=getattr(exc,'container_status',None))
        print('UPLOAD_ONLY_PROBE_ERROR '+str(exc),flush=True)
        raise
    finally:
        archive.save(HISTORY,history)


if __name__=='__main__':
    mode=argparse.ArgumentParser();mode.add_argument('mode',choices=['prepare','upload']);args=mode.parse_args()
    prepare() if args.mode=='prepare' else upload()
