"""Idempotent error-alert ledger in a GitHub Actions run workspace."""
from __future__ import annotations
import hashlib,json,os
from pathlib import Path
LEDGER=Path(os.getenv("NOTIFICATION_DEDUP_PATH","link-runtime/notification-alerts.json"))
def should_send(key:str)->bool:
    if not isinstance(key,str) or not key.strip():raise ValueError("notification key required")
    LEDGER.parent.mkdir(parents=True,exist_ok=True)
    try: data=json.loads(LEDGER.read_text(encoding="utf-8"))
    except FileNotFoundError:data={"sent":[]}
    except (ValueError,OSError):data={"sent":[]}
    sent=data.get("sent",[]) if isinstance(data,dict) else []
    digest=hashlib.sha256(key.encode("utf-8")).hexdigest()
    if digest in sent:return False
    sent.append(digest);data={"sent":sent[-2000:]}
    tmp=LEDGER.with_suffix(".tmp");tmp.write_text(json.dumps(data),encoding="utf-8");os.replace(tmp,LEDGER)
    return True
