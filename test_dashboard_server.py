import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
import dashboard_server as d

class DashboardTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.old=d.ARCHIVE
  d.ARCHIVE=Path(self.tmp.name)/"history.jsonl"
  rows=[]
  for day,views in [("2026-11-01",100),("2026-11-07",140),("2026-11-13",190)]:
   rows.append({"period":day,"account":"Account","platform":"Instagram","entity_type":"account","entity_id":None,"metric":"lifetime_views","value":views,"status":"ok","measured_at":day+"T22:00:00+03:00"})
   rows.append({"period":day,"account":"Account","platform":"Instagram","entity_type":"account","entity_id":None,"metric":"follower_count","value":12,"status":"ok"})
   rows.append({"period":day,"account":"Account","platform":"Instagram","entity_type":"account","entity_id":None,"metric":"snapshot_status","value":2,"status":"ok"})
  d.ARCHIVE.write_text("\n".join(map(json.dumps,rows)),encoding="utf-8")
 def tearDown(self):
  d.ARCHIVE=self.old
  self.tmp.cleanup()
 def test_data_and_period_baselines(self):
  row=d.build_payload()["accounts"][0]
  self.assertEqual(row["current_views"],190)
  self.assertEqual(row["weekly_delta"],50)
  self.assertEqual(row["monthly_delta"],90)
  self.assertEqual(len(row["history"]),3)
 def test_missing_measurement_is_not_zero(self):
  d.ARCHIVE.write_text(json.dumps({"period":"2026-11-13","account":"Account","platform":"Instagram","entity_type":"account","metric":"lifetime_views","value":None,"status":"error"}),encoding="utf-8")
  self.assertIsNone(d.build_payload()["accounts"][0]["current_views"])
 if __name__=="__main__":unittest.main()
