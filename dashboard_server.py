"""Private read-only dashboard API for archived social analytics."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
ARCHIVE = Path(os.getenv("ANALYTICS_ARCHIVE_PATH", ROOT / "dashboard-data" / "daily_video_views.jsonl"))
TZ = ZoneInfo("Europe/Istanbul")
PLATFORMS = ("Facebook", "Instagram", "Facebook 1", "Facebook 2", "YouTube")

def _key():
    return os.getenv("DASHBOARD_PASSWORD", "")

def _authorized(handler):
    expected = _key()
    provided = handler.headers.get("Authorization", "")
    return bool(expected) and hmac.compare_digest(provided, "Bearer " + expected)

def _rows():
    records = []
    try:
        with ARCHIVE.open(encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        pass
    latest = {}
    for r in records:
        if r.get("status") != "ok" or r.get("value") is None:
            continue
        if r.get("metric") not in {"lifetime_views", "follower_count", "snapshot_status", "view_count"}:
            continue
        key=(r.get("period"),r.get("account"),r.get("platform"),r.get("entity_type"),r.get("entity_id"),r.get("metric"))
        latest[key]=r
    return list(latest.values())

def build_payload():
    rows=_rows()
    now=datetime.now(TZ)
    periods={"daily":(now.date()).isoformat(),"weekly":(now.date()).isoformat(),"monthly":(now.date()).isoformat()}
    totals={}
    for r in rows:
        account,platform=r.get("account"),r.get("platform")
        if not account or not platform: continue
        obj=totals.setdefault((account,platform),{"account":account,"platform":platform,"current_views":None,"followers":None,"video_count":None,"status":"ok"})
        if r["metric"]=="lifetime_views" and r.get("entity_type")=="account":
            obj["current_views"]=r["value"];obj["period"]=r.get("period");obj["measured_at"]=r.get("measured_at")
        elif r["metric"]=="follower_count":
            obj["followers"]=r["value"]
        elif r["metric"]=="snapshot_status":
            obj["video_count"]=r["value"]
    snapshots={}
    for r in rows:
        if r["metric"]!="lifetime_views" or r.get("entity_type")!="account": continue
        snapshots[(r.get("account"),r.get("platform"),r.get("period"))]=r["value"]
    for obj in totals.values():
        for p,day in periods.items():
            if p=="daily":
                oldday=(now.date()).isoformat()
            elif p=="weekly":
                from datetime import timedelta
                oldday=(now.date()-timedelta(days=7)).isoformat()
            else:
                oldday=(now.date().replace(day=1)).isoformat()
            base=snapshots.get((obj["account"],obj["platform"],oldday))
            obj[p+"_delta"]=obj["current_views"]-base if obj["current_views"] is not None and base is not None else None
    hist=[]
    for r in rows:
        if r["metric"]=="lifetime_views" and r.get("entity_type")=="account":
            hist.append({"period":r.get("period"),"account":r.get("account"),"platform":r.get("platform"),"metric":"daily","value":r["value"],"status":"ok"})
    measured=max((r.get("measured_at","") for r in rows),default=None)
    return {"measured_at":measured,"accounts":list(totals.values()),"history":hist}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path=="/healthz":
            self.send_response(200);self.end_headers();self.wfile.write(b"ok");return
        if self.path=="/" or self.path=="/index.html":
            body=(ROOT/"dashboard.html").read_bytes()
            self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body);return
        if self.path=="/api/analytics":
            if not _authorized(self):
                self.send_response(401);self.send_header("WWW-Authenticate","Bearer");self.end_headers();return
            body=json.dumps(build_payload(),ensure_ascii=False).encode()
            self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body);return
        self.send_error(404)
    def log_message(self,fmt,*args):
        pass

if not _key():
    raise SystemExit("DASHBOARD_PASSWORD is required")
port=int(os.getenv("PORT","10000"))
ThreadingHTTPServer(("0.0.0.0",port),Handler).serve_forever()
