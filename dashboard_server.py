"""Private, read-only analytics UI. Uses a local cache populated from a secured source."""
from __future__ import annotations
import hmac,json,os
from datetime import date,datetime,timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parent
ARCHIVE=Path(os.getenv("ANALYTICS_ARCHIVE_PATH",ROOT/"dashboard-data"/"daily_video_views.jsonl"))
def authorized(h):
 k=os.getenv("DASHBOARD_PASSWORD","")
 return bool(k) and hmac.compare_digest(h.headers.get("Authorization",""),"Bearer "+k)
def payload():
 data={}
 if ARCHIVE.exists():
  for line in ARCHIVE.open(encoding="utf-8"):
   try:r=json.loads(line)
   except (ValueError,TypeError):continue
   if not isinstance(r,dict):continue
   a,p,d,m,e=r.get("account"),r.get("platform"),r.get("period"),r.get("metric"),r.get("entity_type")
   if a and p and m in {"lifetime_views","follower_count","snapshot_status","engagement_count"}:
    data[(a,p,d,m,e,r.get("entity_id"))]=r
 groups=sorted({(k[0],k[1]) for k in data})
 out=[]
 for a,p in groups:
  days=sorted({k[2] for k in data if k[0]==a and k[1]==p and k[2]})
  day=days[-1] if days else ""
  def val(d,m,e="account"):
   r=data.get((a,p,d,m,e,None))
   return r.get("value") if r and r.get("status")=="ok" else None
  cur=val(day,"lifetime_views")
  row={"account":a,"platform":p,"current_views":cur,"followers":val(day,"follower_count"),
       "video_count":val(day,"snapshot_status"),"status":"ok" if cur is not None else "incomplete",
       "measured_at":(data.get((a,p,day,"lifetime_views","account",None)) or {}).get("measured_at"),
       "latest_day":day,"history":[]}
  for n,delta in (("daily",1),("weekly",7),("monthly",30)):
   try:bday=(date.fromisoformat(day)-timedelta(days=delta)).isoformat()
   except ValueError:bday=""
   base=val(bday,"lifetime_views")
   row[n+"_delta"]=cur-base if type(cur) is int and type(base) is int else None
  for d in days:
   row["history"].append({"date":d,"value":val(d,"lifetime_views")})
  out.append(row)
 return {"measured_at":max((x["measured_at"] or "" for x in out),default=None),"accounts":out}
class H(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path=="/healthz":self.send_response(200);self.end_headers();self.wfile.write(b"ok");return
  if self.path in ("/","/index.html"):
   b=(ROOT/"dashboard.html").read_bytes();self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b);return
  if self.path=="/api/analytics":
   if not authorized(self):self.send_response(401);self.send_header("Cache-Control","no-store");self.end_headers();return
   b=json.dumps(payload(),ensure_ascii=False).encode();self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b);return
  self.send_error(404)
 def log_message(self,*a):pass
if not os.getenv("DASHBOARD_PASSWORD"):raise SystemExit("DASHBOARD_PASSWORD is required")
ThreadingHTTPServer(("0.0.0.0",int(os.getenv("PORT","10000"))),H).serve_forever()
