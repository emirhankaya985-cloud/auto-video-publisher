"""Optional one-shot batch gate for the scheduled publisher.

No batch environment means normal scheduling is unchanged. When configured,
every target must be claimed by the authenticated Worker before any platform
callback is invoked.
"""
import os, requests

class BatchApiError(RuntimeError): pass

class BatchGate:
    def __init__(self, account, platform, drive_file_id, folder_id):
        self.account, self.platform = account, platform
        self.drive_file_id, self.folder_id = drive_file_id, folder_id
        self.batch_id = os.getenv("BATCH_ID")
        self.base = os.getenv("BATCH_API_URL")
        self.token = os.getenv("BATCH_API_TOKEN")
        self.claimed = False
        self.claim_token = None
    @property
    def enabled(self): return bool(self.batch_id and self.base and self.token)
    def claim(self):
        if not self.enabled: return False
        r=requests.post(self.base,headers={"Authorization":f"Bearer {self.token}"},json={"op":"claim","batch_id":self.batch_id,"account":self.account,"platform":self.platform,"drive_file_id":self.drive_file_id,"drive_folder_id":self.folder_id},timeout=20)
        if r.status_code != 200: raise BatchApiError(f"batch claim HTTP {r.status_code}")
        data=r.json(); self.claimed=bool(data.get("claimed")); self.claim_token=data.get("claim_token") if self.claimed else None; return self.claimed
    def finish(self,status,remote_id=None,remote_url=None,error=None):
        if not self.enabled or not self.claimed: return
        requests.post(self.base,headers={"Authorization":f"Bearer {self.token}"},json={"op":"finish","batch_id":self.batch_id,"account":self.account,"platform":self.platform,"claim_token":self.claim_token,"status":status,"remote_id":remote_id,"remote_url":remote_url,"error":error},timeout=20).raise_for_status()
