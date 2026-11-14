"""Password-protected read-only dashboard API over analytics snapshots."""
from __future__ import annotations
import hmac,json,os
from datetime import date,timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parent
ARCHIVE=Path(os.getenv("ANALYTICS_ARCHIVE_PATH",ROOT/"dashboard-data"/"daily_video_views.jsonl"))
def authorized(handler):
    password=os.getenv("DASHBOARD_PASSWORD","")
    return bool(password) and hmac.compare_digest(handler.headers.get("Authorization",""),"Bearer "+password)
def build_payload():
    data={}
    if ARCHIVE.exists():
        with ARCHIVE.open(encoding="utf-8") as src:
            for line in src:
                if not line.strip():continue
                try:r=json.loads(line)
                except (ValueError,TypeError):continue
                if not isinstance(r,dict):continue
                a,p,d,m,e=r.get("account"),r.get("platform"),r.get("period"),r.get("metric"),r.get("entity_type")
                if a and p and m in {"lifetime_views","follower_count","snapshot_status","engagement_count"}:
                    data[(a,p,d,m,e,r.get("entity_id"))]=r
    groups=sorted({(k[0],k[1]) for k in data})
    accounts=[]
    for account,platform in groups:
        days=sorted({k[2] for k in data if k[0]==account and k[1]==platform and isinstance(k[2],str)})
        day=days[-1] if days else ""
        def record(d,metric,entity="account"):
            return data.get((account,platform,d,metric,entity,None))
        def value(d,metric,entity="account"):
            row=record(d,metric,entity)
            val=row.get("value") if row and row.get("status")=="ok" else None
            return val if type(val) is int and val>=0 else None
        current=value(day,"lifetime_views")
        snap=value(day,"snapshot_status")
        measured=record(day,"lifetime_views")
        row={"account":account,"platform":platform,"current_views":current,
             "followers":value(day,"follower_count"),"video_count":snap,
             "status":"ok" if current is not None else "incomplete",
             "measured_at":measured.get("measured_at") if measured else None,
             "latest_day":day,"history":[],"daily_delta":None,
             "weekly_delta":None,"monthly_delta":None,"all_delta":None,
             "data_reason":None if current is not None else "Son snapshot başarısız veya eksik"}
        for period,days_back in (("daily",1),("weekly",7),("monthly",30)):
            try:baseline_day=(date.fromisoformat(day)-timedelta(days=days_back)).isoformat()
            except ValueError:baseline_day=""
            base=value(baseline_day,"lifetime_views")
            row[period+"_delta"]=current-base if current is not None and base is not None else None
        for d in days:
            row["history"].append({"date":d,"value":value(d,"lifetime_views")})
        accounts.append(row)
    measured=max((a.get("measured_at") or "" for a in accounts),default=None)
    return {"measured_at":measured,"accounts":accounts}
payload=build_payload
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path=="/healthz":
            self.send_response(200);self.end_headers();self.wfile.write(b"ok");return
        if self.path in ("/","/index.html"):
            body=(ROOT/"dashboard.html").read_bytes()
            self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body);return
        if self.path=="/api/analytics":
            if not authorized(self):
                self.send_response(401);self.send_header("Cache-Control","no-store");self.end_headers();return
            body=json.dumps(build_payload(),ensure_ascii=False).encode()
            self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body);return
        self.send_error(404)
    def log_message(self,*args):pass
if __name__=="__main__":
    if not os.getenv("DASHBOARD_PASSWORD"):raise SystemExit("DASHBOARD_PASSWORD is required")
    ThreadingHTTPServer(("0.0.0.0",int(os.getenv("PORT","10000"))),H).serve_forever()
