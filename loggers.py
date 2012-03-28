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

# -*- test-case-name: slogger.test.test_loggers -*-

"""
Loggers that log IRC messages
"""
import time

from twisted.internet import defer, threads
from twisted.python import log, logfile

from elasticsearch import ESLogLine
from twisted.internet.task import LoopingCall

current_time, message, user, channel, self.factory.irc_host, event

class LoggingException(Exception):
    pass


def message_to_string(message_time, message, user, channel):
    """
    Generate a message string to be logged

    @param message_time: the time of the message in seconds since the Epoch.
    @type message_time: C{float}

    @param message: the message data
    @type message: C{str}

    @param user: the user who sent the data
    @type user: C{str}

    @param channel: the name of the channel the message was sent on
    @type channel: c{str}
    """
    time_string = time.asctime(time.localtime(message_time))
    return '[%s] %s :  <%s> %s' % (channel, time_string, user, message)


def message_to_dict(message_time, message, user, channel, server=None, action=None):
    """
    Generate a dictionary to be logged

    @param message_time: the time of the message in seconds since the Epoch.
    @type message_time: C{float}

    @param message: the message data
    @type message: C{str}

    @param user: the user who sent the data
    @type user: C{str}

    @param channel: the name of the channel the message was sent on
    @type channel: c{str}
    """

    return {'message': message,
            'user': user,
            'channel': channel,
            'time': message_time,
            'server': server,
            'action': action}


class PyLogger(object):
    """
    Logger that logs messages to stdout
    """
    def log(self, message_time, message, user, channel):
        """
        Logs message, formatted as per L{message_to_string}
        """
        log.msg(message_to_string(message_time, message, user, channel))


class SearchLogger(object):
    """
    Logger that logs messages to elasticsearch
    """
    def log(self, message_time, message, user, channel):
        ESLogLine.objects.create(
            **message_to_dict(message_time, message, user, channel))


class MessageLogger:
    """
    Logger that logs to a file
    """
    def __init__(self, file):
        self.file = file

    def log(self, message_time, message, user, channel):
        self.file.write('%s\n' %
            (message_to_string(message_time, message, user, channel),))
        self.file.flush()

    def close(self):
        self.file.close()


class DailyFileLogger(logfile.DailyLogFile):
    """
    Logger logs everything to one file - it rotates daily

    Initialization is inherited from DailyLogFile:

    @param name: name of the file
    @type name: C{str}

    @param directory: directory holding the file
    @type name: C{str}

    @param defaultMode: permissions used to create the file. Default to
        current permissions of the file if the file exists.
    @type defaultMode: C{int}
    """
    def log(self, message_time, message, user, channel):
        """
        Logs message, formatted as per L{message_to_string}
        """
        self.write('%s\n' %
            (message_to_string(message_time, message, user, channel),))


class MultiChannelFileLogger(object):
    """
    Logger that logs every channel's messages to a different file, which is
    rotated daily.  The exception is system messages, which will be logged to
    its own file, but rotated based on length.
    """

    def __init__(self, directory, channels=None, defaultMode=None,
                 systemRotateLength=1000000):
        """
        Creates one L{DailyFileLogger} logger for each channel in the list,
        and one L{twisted.python.logfile.LogFile} (which rotates based on
        the length of the file) for system messages.

        @param directory: path where all the log files should go
        @type directory: C{str}

        @param channels: a list of channel names
        @type channels: C{list}

        @param defaultMode: mode used to create the files.
        @type defaultMode: C{int}

        @param systemRotateLength: size of the system log file where it
            rotates. Default to 1M.
        @type rotateLength: C{int}
        """
        self._directory = directory
        self._system_logger = logfile.LogFile(
            'system.logs', directory, systemRotateLength, defaultMode)

        self._channel_loggers = {}
        for channel_name in channels:
            self._channel_loggers[channel_name] = DailyFileLogger(
                channel_name, directory, defaultMode)

    def __str__(self):
        return ("Message Logger for channels %s in directory %d" %
            (', '.join(self._channel_loggers.keys()), self._directory))

    def log(self, message_time, message, user, channel):
        """
        If the channel is in the list of channels this logger was initialized
        with, log to the channel's corresponding L{DailyFileLogger}.
        Otherwise, log message as formatted as per L{message_to_string} to the
        system log file.
        """
        if channel in self._channel_loggers:
            self._channel_loggers[channel].log(
                message_time, message, user, channel)
        else:
            formatted_message = ('%s\n' %
                (message_to_string(message_time, message, user, channel),))

            if channel != 'SYSTEM_LOG':
                formatted_message = (
                    '-- Received message from unknown channel:\n\t%s' %
                    (formatted_message,))

            self._system_logger.write(formatted_message)


class BufferedLogger_Mixin(object):
    """
    Mixin to a logger containing functionality to flush its buffered logs
    """
    _buffer = None

    @defer.inlineCallbacks
    def flush(self):
        """
        Write logs in buffer to wherever the normal logging would go
        """
        if not self._buffer:
            newbuffer = []
        else:
            newbuffer = list(self._buffer)

        self._buffer = []

        for msg in newbuffer:
            try:
                yield threads.deferToThread(
                    super(self.__class__, self).log, *msg)

            except Exception as e:
                log('FILE LOGGING FAILED - log: %s excepton: %s' % (log, e))
                self._buffer.append(msg)


class BufferedMultiChannelFileLogger(MultiChannelFileLogger,
                                     BufferedLogger_Mixin):
    """
    Logger that doesn't log right away, but buffers logs and writes them every
    so often
    """

    def __init__(self, directory, channels=None, interval=5, defaultMode=None,
                 systemRotateLength=1000000):
        """
        Same as the initialization for MultiChannelFileLogger, except it takes
        an extra parameter that specifies the interval at which the logs will
        be written to file

        @param interval: number of seconds between writing logs to file.
            Defaults to 5.
        @type interval: C{int}
        """
        super(BufferedMultiChannelFileLogger, self).__init__(
            directory, channels, defaultMode, systemRotateLength)
        self._writeInterval = interval
        self._buffer = []
        self.loop = LoopingCall(self.flush)
        self.loop.start(interval)

    def log(self, message_time, message, user, channel):
        """
        Saves message to buffer, which will be written to file in intervals
        """
        self._buffer.append((message_time, message, user, channel))


class BufferedSearchLogger(SearchLogger, BufferedLogger_Mixin):
    """
    Logger that buffers messages, and eventually logs them to elasticsearch
    """
    def __init__(self, interval=5):
        """
        Same as the initialization for SearchLogger, just with an extra
        interval parameter

        @param interval: number of seconds between writing logs to
            elasticsearch.  Defaults to 5.
        @type interval: C{int}
        """
        super(BufferedSearchLogger, self).__init__()
        self._writeInterval = interval
        self._buffer = []
        self.loop = LoopingCall(self.flush)
        self.loop.start(interval)

    def log(self, message_time, message, user, channel):
        """
        Saves message to buffer, which will be written to file in intervals
        """
        self._buffer.append((message_time, message, user, channel))
