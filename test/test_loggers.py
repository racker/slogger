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

"""
Tests for L{loggers}
"""

import mock

from twisted.trial import unittest
from twisted.internet import reactor, task

import loggers


class MultiChannelFileLoggerTestCase(unittest.TestCase):
    """
    Tests for L{loggers.MultiChannelFileLogger}
    """

    def setUp(self):
        self.patch(loggers, 'DailyFileLogger',
                   mock.MagicMock(loggers.DailyFileLogger))
        self.patch(loggers.logfile, 'LogFile',
                   mock.MagicMock(loggers.logfile.LogFile))

    def test_system_logger_always_created(self):
        """
        Even if no channels are passed, one system
        L{twisted.python.logfile.LogFile} should always be created
        """
        loggers.MultiChannelFileLogger('./', [])
        self.assertEqual(1, loggers.logfile.LogFile.call_count)

    def test_one_logger_created_per_channel(self):
        """
        One L{loggers.DailyFileLogger}logger should be created for each channel
        """
        loggers.MultiChannelFileLogger('./', ['channel1', 'channel2'])
        expected_calls = [mock.call('channel1', './', None),
                          mock.call('channel2', './', None)]
        self.assertEqual(expected_calls, loggers.DailyFileLogger.mock_calls)

    def test_log_to_channel(self):
        """
        When logging a message from a recognized channel, it should be logged
        to its corresponding logger
        """
        filelogger = loggers.MultiChannelFileLogger(
            './', ['channel1', 'channel2'])
        filelogger.log(5.5, 'message', 'user', 'channel1')
        self.assertEqual(
            1, filelogger._channel_loggers['channel1'].log.call_count)
        self.assertFalse(filelogger._system_logger.write.called)

    def test_log_to_system(self):
        """
        When logging a system message, it should be logged to the system logger
        """
        filelogger = loggers.MultiChannelFileLogger('./', ['channel1'])
        filelogger.log(5.5, 'message', 'SYSTEM', 'SYSTEM_LOG')
        self.assertEqual(1, filelogger._system_logger.write.call_count)
        self.assertFalse(filelogger._channel_loggers['channel1'].log.called)

    def test_log_unrecognized_channel(self):
        """
        When logging a message to an unrecognized channel, it should be logged
        to the system logger
        """
        filelogger = loggers.MultiChannelFileLogger('./', ['channel1'])
        filelogger.log(5.5, 'message', 'user', 'channel2')
        self.assertEqual(1, filelogger._system_logger.write.call_count)
        self.assertFalse(filelogger._channel_loggers['channel1'].log.called)


class BufferedMultiChannelFileLoggerTestCase(unittest.TestCase):
    """
    Tests for L{loggers.BufferedMultiChannelFileLogger}
    """

    def setUp(self):
        self.patch(loggers, 'DailyFileLogger',
                   mock.MagicMock(loggers.DailyFileLogger))
        self.patch(loggers.logfile, 'LogFile',
                   mock.MagicMock(loggers.logfile.LogFile))

    def tearDown(self):
        self.logger.loop.stop()

    def _init_file_logger(self, interval):
        self.logger = loggers.BufferedMultiChannelFileLogger(
            './', ['channel1'], interval)
        self.logger.log(5.5, 'message', 'user', 'channel1')
        self.logger.log(5.6, 'message', 'SYSTEM', 'SYSTEM_LOG')

    def test_logs_not_written_immediately(self):
        """
        Logs should not written to immediately
        """
        self._init_file_logger(50)
        self.assertFalse(self.logger._channel_loggers['channel1'].log.called)
        self.assertFalse(self.logger._system_logger.write.called)

    def test_logs_written_after_interval(self):
        """
        Logs should be written all at once after the interval has passed
        """
        self._init_file_logger(.1)

        def _check_if_called():
            self.assertEqual(
                1, self.logger._channel_loggers['channel1'].log.call_count)
            self.assertEqual(1, self.logger._system_logger.write.call_count)

        return task.deferLater(reactor, .2, _check_if_called)


class BufferedSearchLoggerTestCase(unittest.TestCase):
    """
    Tests for L{loggers.BufferedSearchLogger}
    """

    def setUp(self):
        self.patch(loggers.ESLogLine, 'objects',
                   mock.MagicMock(loggers.ESLogLine.objects))

    def tearDown(self):
        self.logger.loop.stop()

    def _init_search_logger(self, interval):
        self.logger = loggers.BufferedSearchLogger(interval)
        self.logger.log(5.5, 'message', 'user', 'channel1')

    def test_logs_not_written_immediately(self):
        self._init_search_logger(50)
        self.assertFalse(loggers.ESLogLine.objects.create.called)

    def test_logs_written_after_interval(self):
        self._init_search_logger(.1)

        def _check_if_called():
            self.assertEqual(1, loggers.ESLogLine.objects.create.call_count)

        return task.deferLater(reactor, .2, _check_if_called)
