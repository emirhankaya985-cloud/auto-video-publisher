import unittest
from pathlib import Path
from unittest.mock import patch
from scheduled_multi_publisher import requested_platform
from cloud_omnichannel_publisher import get_youtube_client

class MetaOnlyModeTests(unittest.TestCase):
    @patch.dict('os.environ', {'YOUTUBE_PUBLISHING_ENABLED': 'false'})
    def test_no_youtube_jobs_even_when_forced(self):
        self.assertFalse(requested_platform('', 'youtube'))
        self.assertFalse(requested_platform('youtube', 'youtube'))
        self.assertTrue(requested_platform('', 'facebook'))
        self.assertTrue(requested_platform('', 'instagram'))

    @patch.dict('os.environ', {'YOUTUBE_PUBLISHING_ENABLED': 'false'})
    def test_youtube_client_fails_before_loading_credentials(self):
        with patch('cloud_omnichannel_publisher.Credentials.from_authorized_user_info') as credentials:
            with self.assertRaisesRegex(RuntimeError, 'devre dışı'):
                get_youtube_client('TOKEN_CHANNEL1_JSON', 'nonexistent.json')
            credentials.assert_not_called()

    def test_meta_publisher_workflow_does_not_probe_deferred_youtube(self):
        workflow = (Path(__file__).parent / '.github' / 'workflows'
                    / 'public_link_schedule.yml').read_text(encoding='utf-8')
        self.assertEqual(workflow.count("YOUTUBE_PUBLISHING_ENABLED: 'false'"), 1)
        self.assertNotIn("YOUTUBE_PUBLISHING_ENABLED: ${{ vars.YOUTUBE_PUBLISHING_ENABLED", workflow)
        # These identity-dependent actions must remain guarded by the disabled flag.
        self.assertIn("env.YOUTUBE_PUBLISHING_ENABLED == 'true'", workflow)
        self.assertIn("steps.youtube_prepare.outcome == 'success'", workflow)
