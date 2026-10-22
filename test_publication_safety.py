import os, unittest
from unittest.mock import patch
from publication_safety import batch_exception_allowed, require_route_enabled, new_meta_route_enabled, route_paused
class Tests(unittest.TestCase):
 def test_existing_routes_can_be_enabled_without_opening_gonle_instagram(self):
  with patch.dict(os.environ, {'ENABLE_TP_NORMAL_ROUTES':'true'}, clear=True):
   self.assertFalse(route_paused('tarladaki'))
   self.assertFalse(route_paused('penguen_ig'))
   self.assertTrue(route_paused('gonle_ig'))
 def test_paused_route_requires_scoped_batch(self):
  with self.assertRaises(RuntimeError): require_route_enabled('tarladaki')
  with patch.dict(os.environ, {'BATCH_ID':'b','BATCH_API_URL':'https://x','BATCH_API_TOKEN':'x','BATCH_ALLOWED_ROUTES':'tarladaki'}): self.assertTrue(batch_exception_allowed('tarladaki'))

 def test_tp_switch_isolated_from_other_existing_routes(self):
  with patch.dict(os.environ, {'ENABLE_TP_NORMAL_ROUTES':'true','ENABLE_EXISTING_ROUTES':'false'}, clear=True):
   self.assertFalse(route_paused('tarladaki'))
   self.assertFalse(route_paused('penguen'))
   self.assertTrue(route_paused('gonle'))
 def test_unlisted_route_denied(self):
  with patch.dict(os.environ, {'BATCH_ID':'b','BATCH_API_URL':'https://x','BATCH_API_TOKEN':'x','BATCH_ALLOWED_ROUTES':'penguen'}): self.assertFalse(batch_exception_allowed('tarladaki'))
 def test_controlled_gonle_instagram_test_is_dispatch_only(self):
  from publication_safety import route_paused, platform_allowed
  with patch.dict(os.environ, {'GITHUB_EVENT_NAME':'workflow_dispatch','FORCE_ROUTE':'gonle_ig','GONLE_IG_CONTROLLED_TEST':'true','ENABLE_GONLE_INSTAGRAM_ROUTES':'true'}, clear=True):
   self.assertFalse(route_paused('gonle_ig'))
   self.assertTrue(platform_allowed('gonle', 'instagram'))

 def test_new_meta_routes_are_disabled_without_both_explicit_switches(self):
  from publication_safety import route_paused
  with patch.dict(os.environ, {}, clear=True):
   self.assertTrue(route_paused('toonzone'))
   self.assertFalse(new_meta_route_enabled('toonzone'))
  with patch.dict(os.environ, {'ENABLE_NEW_META_ROUTES':'true'}, clear=True):
   self.assertTrue(route_paused('toonzone'))
  with patch.dict(os.environ, {'ENABLE_NEW_META_ROUTES':'true', 'META_NEW_ROUTES_RIGHTS_APPROVED':'true'}, clear=True):
   self.assertTrue(route_paused('toonzone'))
   self.assertFalse(new_meta_route_enabled('toonzone'))
  with patch.dict(os.environ, {'ENABLE_NEW_META_ROUTES':'true', 'META_NEW_ROUTES_RIGHTS_APPROVED':'true', 'ENABLE_TOONZONE_ROUTES':'true'}, clear=True):
   self.assertFalse(route_paused('toonzone'))
   self.assertTrue(new_meta_route_enabled('toonzone'))
  with patch.dict(os.environ, {'ENABLE_DAILY_LAUGH_INSTAGRAM_ROUTES':'true'}, clear=True):
   self.assertFalse(route_paused('daily_laugh_instagram'))
   self.assertTrue(new_meta_route_enabled('daily_laugh_instagram'))
  with patch.dict(os.environ, {'GONLE_IG_CONTROLLED_TEST':'true','FORCE_ROUTE':'gonle_ig','ENABLE_GONLE_INSTAGRAM_ROUTES':'true'}, clear=True):
   self.assertFalse(route_paused('gonle_ig'))
  with patch.dict(os.environ, {'GITHUB_EVENT_NAME':'workflow_dispatch','GONLE_IG_CONTROLLED_TEST':'true','FORCE_ROUTE':'gonle_ig'}, clear=True):
   self.assertFalse(route_paused('gonle_ig'))
