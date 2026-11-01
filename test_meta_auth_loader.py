import unittest
from unittest.mock import Mock, patch
import requests
from meta_auth_loader import discover_pages, load_meta_auth


def reply(data, status=200):
    return Mock(status_code=status, json=Mock(return_value=data))


def page(pid='1239298989276639', name='Film Mağarası', token='page-secret'):
    return {'id': pid, 'name': name, 'access_token': token,
            'instagram_business_account': {'id': '1234'}}


class DiscoveryTests(unittest.TestCase):
    def test_user_token_without_json_resolves_known_page(self):
        get = Mock(return_value=reply({'data': [page()]}))
        with patch.dict('os.environ', {'META_ACCESS_TOKEN': 'user-secret'}, clear=True), \
             patch('meta_auth_loader.requests.get', get):
            result = load_meta_auth()
        self.assertEqual(result['pages'][0]['page_token'], 'page-secret')
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
        self.assertNotIn('access_token', get.call_args.kwargs['params'])

    def test_pagination_uses_fixed_host_not_next_url(self):
        get = Mock(side_effect=[reply({'data': [], 'paging': {
            'next': 'https://untrusted.invalid/?token=secret', 'cursors': {'after': 'two'}}}),
            reply({'data': [page()]})])
        self.assertEqual(len(discover_pages('user-secret', get=get)['pages']), 1)
        self.assertEqual(get.call_args.args[0], 'https://graph.facebook.com/v24.0/me/accounts')
        self.assertEqual(get.call_args.kwargs['params']['after'], 'two')

    def test_duplicate_name_is_blocked(self):
        get = Mock(return_value=reply({'data': [page('111', 'Daily Laugh Lab'), page('222', 'Daily Laugh Lab')]}))
        with self.assertRaisesRegex(RuntimeError, 'tekil'):
            discover_pages('user-secret', get=get)

    def test_known_page_name_cannot_substitute_different_id(self):
        with self.assertRaisesRegex(RuntimeError, 'eşleşmedi'):
            discover_pages('secret', get=Mock(return_value=reply({'data': [page('999')]})))

    def test_unknown_pages_are_excluded(self):
        self.assertEqual(discover_pages('secret', get=Mock(return_value=reply({
            'data': [page('999', 'Other account')]}))), {'pages': []})

    def test_rejected_token_does_not_leak_error_body(self):
        with self.assertRaises(RuntimeError) as error:
            discover_pages('secret', get=Mock(return_value=reply({
                'error': {'code': 190, 'message': 'user-secret page-secret'}}, 400)))
        self.assertNotIn('secret', str(error.exception))
        self.assertIn('190', str(error.exception))

    def test_auth_190_expired_subcode_is_numeric_only_and_never_leaks_body(self):
        get = Mock(return_value=reply({
            'error': {'code': 190, 'error_subcode': 463,
                      'message': 'USER_SECRET PAGE_SECRET raw-provider-message'}}, 401))
        with self.assertRaises(RuntimeError) as ctx:
            discover_pages('USER_SECRET', get=get)
        result = str(ctx.exception)
        self.assertIn('HTTP 401', result)
        self.assertIn('kod 190', result)
        self.assertIn('alt_kod 463', result)
        self.assertNotIn('USER_SECRET', result)
        self.assertNotIn('PAGE_SECRET', result)
        self.assertNotIn('raw-provider-message', result)

    def test_auth_unknown_subcode_is_not_interpreted_as_expiry(self):
        get = Mock(return_value=reply({'error': {
            'code': 190, 'error_subcode': 'not-a-number',
            'message': 'DO_NOT_PRINT_ME'}}, 401))
        with self.assertRaises(RuntimeError) as ctx:
            discover_pages('USER_SECRET', get=get)
        result = str(ctx.exception)
        self.assertIn('alt_kod unknown', result)
        self.assertNotIn('DO_NOT_PRINT_ME', result)

    def test_network_exception_does_not_leak_url_or_token(self):
        with self.assertRaises(RuntimeError) as error:
            discover_pages('secret', get=Mock(side_effect=requests.RequestException('secret URL')))
        self.assertNotIn('secret', str(error.exception))

    def test_user_token_takes_priority_over_legacy_bundle(self):
        pages = {'pages': [page()]}
        with patch.dict('os.environ', {
            'META_ACCESS_TOKEN': 'user-secret',
            'META_AUTH_JSON': '{"pages": []}',
        }, clear=True), patch('meta_auth_loader.discover_pages', return_value=pages) as discover:
            self.assertEqual(load_meta_auth(), pages)
        discover.assert_called_once_with('user-secret')

    def test_malformed_legacy_bundle_is_ignored_without_logging_it(self):
        pages = {'pages': [page()]}
        with patch.dict('os.environ', {
            'META_ACCESS_TOKEN': 'user-secret',
            'META_AUTH_JSON': 'malformed-secret-content',
        }, clear=True), patch('meta_auth_loader.discover_pages', return_value=pages) as discover:
            self.assertEqual(load_meta_auth(), pages)
        discover.assert_called_once_with('user-secret')

    def test_no_user_token_fails_closed_even_if_legacy_bundle_is_present(self):
        with patch.dict('os.environ', {'META_AUTH_JSON': '{"pages": []}'}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'META_ACCESS_TOKEN eksik'):
                load_meta_auth()

    def test_user_token_discovery_failure_never_uses_legacy_bundle(self):
        with patch.dict('os.environ', {
            'META_ACCESS_TOKEN': 'expired-secret',
            'META_AUTH_JSON': '{"pages": []}',
        }, clear=True), patch('meta_auth_loader.discover_pages',
                            side_effect=RuntimeError('Meta hesap erişimi reddedildi (HTTP 401, kod 190, alt_kod 463)')) as discover:
            with self.assertRaisesRegex(RuntimeError, 'HTTP 401, kod 190, alt_kod 463'):
                load_meta_auth()
        discover.assert_called_once_with('expired-secret')


if __name__ == '__main__':
    unittest.main()
