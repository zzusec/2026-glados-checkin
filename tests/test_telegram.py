import os
import unittest
from unittest import mock

import requests

import checkin


TOKEN = 'synthetic-private-bot-token'
CHAT_ID = '123456789'


class TelegramPushTests(unittest.TestCase):
    @mock.patch('checkin.requests.post')
    def test_sends_compatible_html_and_requires_api_acknowledgement(self, post):
        post.return_value = mock.Mock(status_code=200)
        post.return_value.json.return_value = {'ok': True, 'result': {'message_id': 1}}

        self.assertTrue(checkin.telegram_push(
            TOKEN, CHAT_ID, 'Check-in test',
            '<div><h3>Account</h3><p><span>Failed</span><br>Retry later</p></div>',
        ))

        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], f'https://api.telegram.org/bot{TOKEN}/sendMessage')
        self.assertEqual(kwargs['json']['chat_id'], CHAT_ID)
        self.assertEqual(kwargs['json']['parse_mode'], 'HTML')
        self.assertIn('<b>Check-in test</b>', kwargs['json']['text'])
        self.assertIn('<b>Account</b>', kwargs['json']['text'])
        self.assertIn('Failed\nRetry later', kwargs['json']['text'])
        for tag in ('<div', '<h3', '<p>', '<span', '<br>'):
            self.assertNotIn(tag, kwargs['json']['text'])

    @mock.patch('checkin.requests.post')
    def test_partial_configuration_does_not_send(self, post):
        self.assertFalse(checkin.telegram_push('', CHAT_ID, 'Test', 'Body'))
        self.assertFalse(checkin.telegram_push(TOKEN, '', 'Test', 'Body'))
        post.assert_not_called()

    @mock.patch('checkin.log')
    @mock.patch('checkin.requests.post')
    def test_http_failure_does_not_log_response_body(self, post, log):
        post.return_value = mock.Mock(status_code=403)
        post.return_value.json.return_value = {'description': TOKEN}

        self.assertFalse(checkin.telegram_push(TOKEN, CHAT_ID, 'Test', 'Body'))

        self.assertIn('HTTP 403', str(log.call_args_list))
        self.assertNotIn(TOKEN, str(log.call_args_list))
        post.return_value.json.assert_not_called()

    @mock.patch('checkin.log')
    @mock.patch('checkin.requests.post')
    def test_success_http_status_without_ok_true_is_failure(self, post, log):
        for payload in ({'ok': False, 'description': TOKEN}, {}, [], {'ok': 'true'}):
            with self.subTest(payload=payload):
                post.return_value = mock.Mock(status_code=200)
                post.return_value.json.return_value = payload
                self.assertFalse(checkin.telegram_push(TOKEN, CHAT_ID, 'Test', 'Body'))
        self.assertNotIn(TOKEN, str(log.call_args_list))
        self.assertNotIn('✅', str(log.call_args_list))

    @mock.patch('checkin.log')
    @mock.patch('checkin.requests.post')
    def test_network_exception_never_logs_token_in_request_url(self, post, log):
        post.side_effect = requests.ConnectionError(
            f'Unable to connect to https://api.telegram.org/bot{TOKEN}/sendMessage'
        )

        self.assertFalse(checkin.telegram_push(TOKEN, CHAT_ID, 'Test', 'Body'))

        self.assertIn('ConnectionError', str(log.call_args_list))
        self.assertNotIn(TOKEN, str(log.call_args_list))
        self.assertNotIn('api.telegram.org/bot', str(log.call_args_list))

    @mock.patch('checkin.log')
    @mock.patch('checkin.requests.post')
    def test_invalid_json_response_never_logs_private_details(self, post, log):
        post.return_value = mock.Mock(status_code=200)
        post.return_value.json.side_effect = ValueError(TOKEN)

        self.assertFalse(checkin.telegram_push(TOKEN, CHAT_ID, 'Test', 'Body'))

        self.assertIn('ValueError', str(log.call_args_list))
        self.assertNotIn(TOKEN, str(log.call_args_list))


class TelegramFailureAlertTests(unittest.TestCase):
    @mock.patch('checkin.log')
    @mock.patch('checkin.telegram_push', return_value=True)
    def test_failure_only_alerts_once_and_success_stays_silent(self, telegram, log):
        for failed_account in (None, 1):
            with self.subTest(failed_account=failed_account):
                telegram.reset_mock()
                clients = [
                    mock.Mock(email=f'private-{i}@example.test', points='100', left_days='30',
                              points_change='+5', exchange_info='', exchange_result='')
                    for i in range(3)
                ]
                for i, client in enumerate(clients):
                    client.checkin.return_value = (
                        {'code': -2, 'message': 'Permission denied'} if i == failed_account
                        else {'code': 0, 'message': 'Checkin! Got 5 Points'}
                    )
                cookies = [f'gld:sess=private-{i}; gld:sess.sig=signature-{i}' for i in range(3)]
                env = {
                    'GLADOS_COOKIE': '\n'.join(cookies),
                    'GLADOS_EXPECTED_ACCOUNTS': '3',
                    'TELEGRAM_BOT_TOKEN': TOKEN,
                    'TELEGRAM_CHAT_ID': CHAT_ID,
                    'PUSH_LEVEL': 'fail_only',
                    'EXCHANGE_PLAN': 'off',
                }
                with mock.patch.dict(os.environ, env, clear=True), \
                        mock.patch('checkin.GLaDOS', side_effect=clients):
                    self.assertEqual(checkin.main(), int(failed_account is not None))
                if failed_account is None:
                    telegram.assert_not_called()
                else:
                    telegram.assert_called_once()
                    token, chat_id, title, content = telegram.call_args.args
                    self.assertEqual((token, chat_id), (TOKEN, CHAT_ID))
                    self.assertIn('成功2/3', title)
                    self.assertIn('Permission denied', content)
                    for cookie in cookies:
                        self.assertNotIn(cookie, content)
                for client in clients:
                    client.checkin.assert_called_once_with()
                    client.exchange.assert_not_called()
        self.assertNotIn(TOKEN, str(log.call_args_list))
        self.assertNotIn('@example.test', str(log.call_args_list))


if __name__ == '__main__':
    unittest.main()
