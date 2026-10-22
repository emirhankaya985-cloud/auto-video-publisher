import os, unittest
from datetime import datetime
from unittest.mock import patch
from publication_safety import route_paused, batch_exception_allowed
from scheduled_multi_publisher import due_slots, DRIVE_ROUTE_SPECS, folder_for_route

class NewYoutubeRouteTests(unittest.TestCase):
    def test_routes_disabled_by_default_and_batch_cannot_bypass(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(route_paused('gonle_youtube'))
            self.assertTrue(route_paused('daily_laugh_youtube'))
        with patch.dict(os.environ, {'BATCH_ID':'x','BATCH_API_URL':'https://worker','BATCH_API_TOKEN':'secret','BATCH_ALLOWED_ROUTES':'gonle_youtube'}, clear=True):
            self.assertFalse(batch_exception_allowed('gonle_youtube'))

    def test_new_youtube_uses_existing_parent_slots(self):
        when=datetime(2026,10,16,12,45)
        with patch.dict(os.environ, {}, clear=True):
            routes={r for _,r,_ in due_slots(when)}
            self.assertIn('gonle', routes)
            self.assertIn('daily_laugh', routes)
        with patch.dict(os.environ, {'ENABLE_NEW_YOUTUBE_ROUTES':'true'}, clear=True):
            routes={r for _,r,_ in due_slots(when)}
            self.assertIn('gonle', routes)

    def test_daily_laugh_parent_slot_is_retained_for_english_fanout(self):
        when=datetime(2026,10,16,18,45)
        with patch.dict(os.environ, {'ENABLE_NEW_YOUTUBE_ROUTES':'true'}, clear=True):
            routes={r for _,r,_ in due_slots(when)}
        self.assertIn('daily_laugh', routes)

    def test_new_youtube_routes_are_paused_until_explicit_enablement(self):
        with patch.dict(os.environ, {'ENABLE_NEW_YOUTUBE_ROUTES':'false'}, clear=True):
            self.assertTrue(route_paused('gonle_youtube'))
            self.assertTrue(route_paused('daily_laugh_youtube'))
        with patch.dict(os.environ, {'ENABLE_NEW_YOUTUBE_ROUTES':'true'}, clear=True):
            self.assertFalse(route_paused('gonle_youtube'))
            self.assertFalse(route_paused('daily_laugh_youtube'))

    def test_drive_allowlist_values_are_expected(self):
        self.assertEqual(DRIVE_ROUTE_SPECS['gonle'][1], '1OA-qvfBEcCKBCTSMj4dCz8rg2p6t0aKt')
        self.assertEqual(DRIVE_ROUTE_SPECS['daily_laugh'][1], '137--TeBht1yikZpMfV9VSEADbKuXZtLT')

    def test_each_new_youtube_route_selects_its_own_drive_folder(self):
        values = {
            'GONLE_DUSEN_DRIVE_FOLDER_ID': '1OA-qvfBEcCKBCTSMj4dCz8rg2p6t0aKt',
            'DAILY_LAUGH_DRIVE_FOLDER_ID': '137--TeBht1yikZpMfV9VSEADbKuXZtLT',
        }
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(folder_for_route(None, 'gonle_youtube', 'slot'), values['GONLE_DUSEN_DRIVE_FOLDER_ID'])
            self.assertEqual(folder_for_route(None, 'daily_laugh_youtube', 'slot'), values['DAILY_LAUGH_DRIVE_FOLDER_ID'])
