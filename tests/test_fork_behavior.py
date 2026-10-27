import json
import os
from pathlib import Path
import unittest
from unittest import mock

import checkin


COOKIES = [
    f'gld:sess=account-{i}; gld:sess.sig=signature-{i}'
    for i in range(1, 4)
]
COOKIE_ENV = dict(zip(('GLADOS_COOKIE', 'GLADOS_COOKIE_2', 'GLADOS_COOKIE_3'), COOKIES))


class MultiAccountTests(unittest.TestCase):
    def test_three_separate_secrets_are_read_in_order(self):
        with mock.patch.dict(os.environ, COOKIE_ENV, clear=True):
            self.assertEqual(checkin.get_cookies(), COOKIES)

    def test_secondary_secret_works_without_primary(self):
        with mock.patch.dict(os.environ, {'GLADOS_COOKIE_2': COOKIES[1]}, clear=True):
            self.assertEqual(checkin.get_cookies(), [COOKIES[1]])

    def test_separate_formatted_exports_do_not_merge(self):
        env = {}
        for i, name in enumerate(COOKIE_ENV, 1):
            env[name] = json.dumps([
                {'name': 'gld:sess', 'value': f'account-{i}'},
                {'name': 'gld:sess.sig', 'value': f'signature-{i}'},
            ], indent=2)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(checkin.get_cookies(), COOKIES)

    def test_ampersands_and_newlines_work_with_separate_secrets(self):
        env = {
            'GLADOS_COOKIE': '&'.join(COOKIES[:2]) + '\n',
            'GLADOS_COOKIE_3': COOKIES[2],
        }
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(checkin.get_cookies(), COOKIES)

    @mock.patch('checkin.GLaDOS')
    def test_missing_or_invalid_account_fails_before_api_calls(self, client_class):
        for invalid in ('', '[\n{\n'):
            env = {**COOKIE_ENV, 'GLADOS_COOKIE_2': invalid, 'GLADOS_EXPECTED_ACCOUNTS': '3'}
            with self.subTest(invalid=invalid), mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(checkin.main(), 1)
        client_class.assert_not_called()

    @mock.patch('checkin.GLaDOS')
    def test_extra_account_fails_before_api_calls(self, client_class):
        env = {
            **COOKIE_ENV,
            'GLADOS_COOKIE': '\n'.join(COOKIES[:2]),
            'GLADOS_EXPECTED_ACCOUNTS': '3',
        }
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(checkin.main(), 1)
        client_class.assert_not_called()

    @mock.patch('checkin.GLaDOS')
    def test_diagnostic_checks_all_three_and_fails_if_one_is_rejected(self, client_class):
        client_class.return_value.req.side_effect = [
            {'code': 0, 'data': {'leftDays': 30}},
            {'code': -2, 'message': 'denied'},
            {'code': 0, 'data': {'leftDays': 60}},
        ]
        env = {**COOKIE_ENV, 'GLADOS_EXPECTED_ACCOUNTS': '3', 'CHECKIN_DIAGNOSTIC_ONLY': 'true'}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(checkin.main(), 1)
        self.assertEqual(client_class.call_args_list, [mock.call(cookie) for cookie in COOKIES])
        self.assertEqual(client_class.return_value.req.call_count, 3)
        client_class.return_value.checkin.assert_not_called()
        client_class.return_value.exchange.assert_not_called()

    @mock.patch('checkin.log')
    def test_real_run_processes_all_accounts_and_never_exchanges_by_default(self, log):
        for failed_account in (None, 1):
            with self.subTest(failed_account=failed_account):
                clients = [
                    mock.Mock(email=f'private-{i}@example.test', points='5000', left_days='30',
                              points_change='+5', exchange_info='', exchange_result='')
                    for i in range(3)
                ]
                for i, client in enumerate(clients):
                    client.checkin.return_value = (
                        {'code': -2, 'message': 'denied'} if i == failed_account
                        else {'code': 0, 'message': 'Checkin! Got 5 Points'}
                    )
                env = {**COOKIE_ENV, 'GLADOS_EXPECTED_ACCOUNTS': '3'}
                with mock.patch.dict(os.environ, env, clear=True), \
                        mock.patch('checkin.GLaDOS', side_effect=clients) as client_class:
                    self.assertEqual(checkin.main(), int(failed_account is not None))
                self.assertEqual(client_class.call_args_list, [mock.call(cookie) for cookie in COOKIES])
                for client in clients:
                    client.checkin.assert_called_once_with()
                    client.exchange.assert_not_called()
        printed = str(log.call_args_list)
        for cookie in COOKIES:
            self.assertNotIn(cookie, printed)
        self.assertNotIn('@example.test', printed)


class DeviceCorrectionTests(unittest.TestCase):
    def test_macos_is_the_default_login_device(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            headers = checkin.get_browser_headers()
        self.assertEqual(headers['Sec-CH-UA-Platform'], '"macOS"')

    @mock.patch('checkin.requests.post')
    def test_device_correction_updates_user_agent_and_client_hints(self, post):
        failure = mock.Mock(status_code=200)
        failure.json.return_value = {'code': 4, 'reason': 'device-mismatch', 'loginDevice': 'Windows'}
        success = mock.Mock(status_code=200)
        success.json.return_value = {'code': 0, 'message': 'Checkin! Got 5 Points'}
        post.side_effect = [failure, success]
        with mock.patch.dict(os.environ, {}, clear=True):
            client = checkin.GLaDOS(COOKIES[0])
            self.assertEqual(client.checkin()['code'], 0)
        self.assertEqual(post.call_count, 2)
        first, second = [call.kwargs['headers'] for call in post.call_args_list]
        self.assertEqual(first['Sec-CH-UA-Platform'], '"macOS"')
        self.assertIn('Windows NT', second['User-Agent'])
        self.assertEqual(second['Sec-CH-UA-Platform'], '"Windows"')
        self.assertIn('v="154"', second['Sec-CH-UA'])
        self.assertEqual(second['Cookie'], COOKIES[0])

    def test_corrected_device_is_private_to_each_account(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            first = checkin.GLaDOS(COOKIES[0])
            second = checkin.GLaDOS(COOKIES[1])
        with mock.patch.object(first, 'req', side_effect=[
            {'code': 4, 'reason': 'device-mismatch', 'loginDevice': 'Windows'},
            {'code': 0},
        ]):
            self.assertEqual(first.checkin()['code'], 0)
        self.assertNotEqual(first.user_agent, second.user_agent)
        self.assertEqual(second.user_agent, checkin.DEFAULT_USER_AGENT)

    def test_windows_to_macos_correction_works_with_one_attempt(self):
        with mock.patch.dict(os.environ, {'GLADOS_USER_AGENT': checkin.DEVICE_USER_AGENTS['windows']}, clear=True):
            client = checkin.GLaDOS(COOKIES[0])
        with mock.patch.object(client, 'req', side_effect=[
            {'code': 4, 'reason': 'device-mismatch', 'loginDevice': 'macOS'},
            {'code': 0},
        ]) as req:
            result, success = checkin.checkin_with_retry(client, attempts=1)
        self.assertTrue(success)
        self.assertEqual(result['code'], 0)
        self.assertEqual(req.call_count, 2)
        self.assertEqual(checkin.get_browser_headers(client.user_agent)['Sec-CH-UA-Platform'], '"macOS"')

    def test_unknown_missing_or_unchanged_login_device_does_not_retry(self):
        for device in ('unknown', None, '', 'macOS'):
            with self.subTest(device=device), mock.patch.dict(os.environ, {}, clear=True):
                client = checkin.GLaDOS(COOKIES[0])
                failure = {'code': 4, 'reason': 'device-mismatch', 'loginDevice': device}
                with mock.patch.object(client, 'req', return_value=failure) as req:
                    self.assertEqual(client.checkin(), failure)
                self.assertEqual(req.call_count, 1)

    def test_repeated_mismatch_stops_after_one_correction(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            client = checkin.GLaDOS(COOKIES[0])
        failure = {'code': 4, 'reason': 'device-mismatch', 'loginDevice': 'Windows'}
        with mock.patch.object(client, 'req', return_value=failure) as req:
            result, success = checkin.checkin_with_retry(client)
        self.assertFalse(success)
        self.assertEqual(result, failure)
        self.assertEqual(req.call_count, 2)

    @mock.patch('checkin.time.sleep')
    def test_transient_failure_does_not_allow_a_second_device_correction(self, sleep):
        with mock.patch.dict(os.environ, {}, clear=True):
            client = checkin.GLaDOS(COOKIES[0])
        failure = {'code': 4, 'reason': 'device-mismatch', 'loginDevice': 'macOS'}
        with mock.patch.object(client, 'req', side_effect=[
            {'code': 4, 'reason': 'device-mismatch', 'loginDevice': 'Windows'},
            None,
            failure,
        ]) as req:
            result, success = checkin.checkin_with_retry(client, attempts=3, delay_seconds=1)
        self.assertFalse(success)
        self.assertEqual(result, failure)
        self.assertEqual(req.call_count, 3)
        self.assertEqual(client.user_agent, checkin.DEVICE_USER_AGENTS['windows'])
        sleep.assert_called_once_with(1)

    def test_expired_session_does_not_trigger_device_correction(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            client = checkin.GLaDOS(COOKIES[0])
        failure = {'code': -2, 'message': 'denied'}
        with mock.patch.object(client, 'req', return_value=failure) as req:
            result, success = checkin.checkin_with_retry(client)
        self.assertFalse(success)
        self.assertEqual(result, failure)
        self.assertEqual(req.call_count, 1)


class WorkflowContractTests(unittest.TestCase):
    def test_workflow_passes_three_secrets_and_checks_expected_count(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/checkin.yml').read_text()
        for name in COOKIE_ENV:
            self.assertIn(f'{name}: ${{{{ secrets.{name} }}}}', workflow)
        self.assertIn("GLADOS_EXPECTED_ACCOUNTS: '3'", workflow)
        self.assertIn("EXCHANGE_PLAN: ${{ vars.EXCHANGE_PLAN || 'off' }}", workflow)
        self.assertIn("cron: '30 1 * * *'", workflow)
        self.assertIn("cron: '30 13 * * *'", workflow)


if __name__ == '__main__':
    unittest.main()
