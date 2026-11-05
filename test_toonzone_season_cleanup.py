import unittest
from unittest.mock import Mock, patch
import toonzone_season_cleanup as cleanup


class Tests(unittest.TestCase):
    def record(self, **changes):
        result = dict(route='toonzone', user_id='7', file='S01E01_The_Power_Part1.mp4',
                      post_id='123', status='verified', permalink='https://example.invalid/post')
        result.update(changes)
        return result

    def test_only_exact_campaign_posts_on_verified_account_are_selected(self):
        result = cleanup.targets({'records': {'a': self.record(), 'b': {'status': 'reserved'}}}, 'instagram', '7')
        self.assertEqual([i['post_id'] for i in result], ['123'])
        for changes in ({'user_id': '8'}, {'route': 'film'}, {'file': 'S02E01_Title_Part1.mp4'}, {'post_id': 'bad'}):
            with self.assertRaises(RuntimeError):
                cleanup.targets({'records': {'a': self.record(**changes)}}, 'instagram', '7')

    def test_delete_is_one_request_with_bearer_header_and_no_redirect(self):
        response = Mock(status_code=200)
        response.json.return_value = {'success': True}
        with patch.object(cleanup.requests, 'delete', return_value=response) as delete:
            result = cleanup.delete_once('https://graph.facebook.com/v24.0', 'secret', '123')
        self.assertEqual(result['status'], 'delete_accepted')
        delete.assert_called_once()
        self.assertEqual(delete.call_args.args[0], 'https://graph.facebook.com/v24.0/123')
        self.assertFalse(delete.call_args.kwargs['allow_redirects'])
        self.assertNotIn('secret', delete.call_args.args[0])

    def test_permission_rejection_is_recorded_without_claiming_deletion(self):
        response = Mock(status_code=400)
        response.json.return_value = {'error': {'code': 10}}
        with patch.object(cleanup.requests, 'delete', return_value=response):
            result = cleanup.delete_once('https://graph.facebook.com/v24.0', 'secret', '123')
        self.assertEqual(result, {'status': 'delete_rejected', 'http_status': 400, 'code': 10, 'subcode': None})


if __name__ == '__main__':
    unittest.main()
