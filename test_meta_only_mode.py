import unittest
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
