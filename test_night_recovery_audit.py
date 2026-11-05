import unittest
from unittest.mock import patch
import night_recovery_audit as audit
import toonzone_season_cleanup as cleanup


class NightReadOnlyTests(unittest.TestCase):
    def test_cancelled_campaign_audit_counts_only_bound_old_ids_without_deleting(self):
        with patch.object(cleanup, 'connection', return_value=('unused', 'test', '123', {})), \
             patch.object(cleanup.archive, 'restore', return_value={'records': {}}), \
             patch.object(cleanup, 'targets', return_value=[{'post_id': '1'}, {'post_id': '2'}]), \
             patch.object(cleanup, 'owned_posts', return_value=[{'id': '2'}, {'id': '3'}]), \
             patch.object(cleanup.requests, 'delete') as delete:
            result = audit.cancelled_instagram_posts()
        self.assertEqual(result, {'status': 'checked', 'campaign_posts': 2,
                                 'still_visible': 1, 'deletions_attempted': 0})
        delete.assert_not_called()


if __name__ == '__main__':
    unittest.main()
