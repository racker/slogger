# Copyright 2012 Rackspace

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock

from twisted.trial import unittest

import bot


class LogBotTestCase(unittest.TestCase):
    """
    Tests for L{bot.LogBot}
    """

    def setUp(self):
        for logger in ('PyLogger', 'BufferedSearchLogger',
                       'BufferedMultiChannelFileLogger'):
            self.patch(bot.loggers, logger, mock.MagicMock(['log']))

    def _make_mock_logbot(self, channels, dirpath='./'):
        """
        Initialize a fake logbot (to use as self to functions) and set the
        factory to a fake factory.
        """
        fake_factory = mock.MagicMock(channels=channels, log_path=dirpath)
        self.fake_logbot = mock.MagicMock(bot.LogBot,
                                          factory=fake_factory)

    def test_join_all_channels_on_signon(self):
        """
        On signing on to the server, the bot should join all of the channels in
        the channel list
        """
        channels = ['#channel1', '#channel2']
        self._make_mock_logbot(channels)

        # mock calling a LogBot().signedOn(), but with a fake logbot as self
        bot.LogBot.signedOn.im_func(self.fake_logbot)

        expected_calls = [mock.call(name) for name in channels]
        self.assertEqual(expected_calls, self.fake_logbot.join.mock_calls)

    def _run_connection_made(self):
        """
        Fake calls connection made, for the tests to see if a logger is created
        """
        self.channels = ['#channel1', '#channel2']
        self._make_mock_logbot(self.channels)
        # mock calling LogBot().connectionMade()
        bot.LogBot.connectionMade.im_func(self.fake_logbot)

    def test_connection_made_PyLogger(self):
        """
        When a connection is made, a PyLogger should be created
        """
        self._run_connection_made()
        bot.loggers.PyLogger.assert_called_once_with()

    def test_connection_made_BufferedSearchLogger(self):
        """
        When a connection is made, a BufferedSearchLogger should be created
        """
        self._run_connection_made()
        bot.loggers.BufferedSearchLogger.assert_called_once_with()

    def test_connection_made_BufferedMultiChannelFileLogger(self):
        """
        When a connection is made, a BufferedMultiChannelFileLogger should be
        created
        """
        self._run_connection_made()
        bot.loggers.BufferedMultiChannelFileLogger.assert_called_once_with(
            './', self.channels)

    def test_write_log(self):
        """
        LogBot().writeLog should log the same message to all available loggers
        """
        self.channels = ['#channel1', '#channel2']
        self._make_mock_logbot(self.channels)
        self.fake_logbot.loggers = [
            bot.loggers.PyLogger(),
            bot.loggers.BufferedSearchLogger(),
            bot.loggers.BufferedMultiChannelFileLogger()
        ]
        # mock calling LogBot().writeLog()
        bot.LogBot.writeLog.im_func(
            self.fake_logbot, "message", "user", "channel1")

        calls = None
        for logger in self.fake_logbot.loggers:
            if not calls:
                calls = logger.log.mock_calls
                self.assertEqual(1, len(calls))
            else:
                self.assertEqual(calls, logger.mock_calls)

    def test_user_join_is_logged(self):
        """
        Message should be logged when a user joins the channel
        """
        self._make_mock_logbot(['#channel1'])
        # mock calling LogBot.userJoined()
        bot.LogBot.userJoined.im_func(self.fake_logbot, 'me', '#channel1')
        self.assertEqual(1, self.fake_logbot.writeLog.call_count)
        # mock.call_args[0] = non-keyword arguments ([1] is keyword arguments)
        self.assertEqual((None, '#channel1'),
                         self.fake_logbot.writeLog.call_args[0][1:])

    def test_user_left_is_logged(self):
        """
        Message should be logged when a user leaves the channel
        """
        self._make_mock_logbot(['#channel1'])
        # mock calling LogBot.userJoined()
        bot.LogBot.userLeft.im_func(self.fake_logbot, 'me', '#channel1')
        self.assertEqual(1, self.fake_logbot.writeLog.call_count)
        # mock.call_args[0] = non-keyword arguments ([1] is keyword arguments)
        self.assertEqual((None, '#channel1'),
                         self.fake_logbot.writeLog.call_args[0][1:])
