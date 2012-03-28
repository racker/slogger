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

# -*- test-case-name: slogger.test.test_bot -*-

import time

from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from twisted.python import log

import settings
import loggers
from events import *
from elasticsearch import ESLogLine


class LogBot(irc.IRCClient):

    nickname = settings.NICK[:16]
    ignorelist = []
    _user_left_FP = None
    log_user = "af3aF&G@#*@#*(#@#*(@&&FHU#IU#HJAF#(@F@#J"

    def writeLog(self, user, channel, event, message=None):
        current_time = time.time()
        msg = (current_time, user, channel, event, self.factory.irc_host, message)
        for logger in self.loggers:
            logger.log(*msg)

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        self.loggers = [
            loggers.PyLogger(),
            loggers.BufferedMultiChannelFileLogger(
                self.factory.log_path, self.factory.channels),
            loggers.BufferedSearchLogger()]

        self.writeLog(self.log_user, None, CONNECT_EVENT)

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self, reason)
        self.writeLog(self.log_user, None, DISCONNECT_EVENT)

    def signedOn(self):
        """Called when bot has succesfully signed on to server."""
        self.setNick(self._attemptedNick)
        for channel_name in self.factory.channels:
            self.join(channel_name)

    def joined(self, channel):
        """This will get called when the bot joins the channel."""
        self.writeLog(self.log_user, channel, JOIN_EVENT)

    def privmsg(self, user, channel, msg):
        """This will get called when the bot receives a message."""
        user = user.split('!', 1)[0]
        self.writeLog(user, channel, MSG_EVENT, msg)
        self.handle_command(user, channel, msg)

    def userJoined(self, user, channel):
        """
        When the user joins a channel, log the join
        """
        self.writeLog(user, channel, JOIN_EVENT)
        # TODO: this is temporary
        if not self._user_is_self(user):
            last_exit_dict = self._get_user_last_exit_time(user, channel)
            last_exit_time = last_exit_dict.get(channel, None)
            self.msg(user, (
                "The last time you left this channel was: %s. "
                "Please see the history since you left here: %s" % (
                    time.asctime(time.localtime(last_exit_time)),
                    'this is not ready yet')))

    def userLeft(self, user, channel):
        """
        When the user leaves a channel, log the leave
        """
        self.writeLog(user, channel, LEAVE_EVENT)

    def _user_is_self(self, user):
        """
        Is this user the bot?  Currently there is no good way of determining
        what the server thinks the bot's username is (if it's truncated for
        instance).  So right now, check it against the nick, and hope for the
        best.

        @param user: username
        @type user: C{str}

        @return: true if the user is the logbot, false otherwise
        """
        return user == self.nickname

    def _get_user_last_exit_time(self, user, channel=None):
        """
        When the user last exited this channel.  This should probably go
        elsewhere.  Also, async.

        @param user: the username of the user
        @type user: C{str}

        @param channel: the channel that we want to get the last exit time for.
            If not provided, will return the last exit times for all the
            all the channels that was recorded for that user
        @type channel: C{str}

        @return: C{dict} mapping channel names to exit times in seconds since
            the epoch
        """
        results = {}
        return results

    # Commands

    def handle_command(self, user, channel, msg):

        reply_to = None

        # PM
        if channel == self.nickname:
            reply_to = user

        # Mentioned in channel
        if msg.startswith(self.nickname + ":"):
            msg = msg[len(self.nickname) + 1:]
            reply_to = channel

        if reply_to:
            msg = msg.strip()
            split = msg.split(None, 1)
            command = split[0]
            try:
                args = split[1]
            except IndexError:
                args = None

            # TODO: Plugin system and shit
            if command.lower() == 'help':
                if args == 'search':
                    reply = 'search <lucene query> - searches for messages'
                elif args == 'ignore':
                    reply = 'ignore <optional: nick> - ignores you, or a given nick'
                elif args == 'unignore':
                    reply = 'unignore <optional: nick> - unignores you, or a given nick'
                elif args == 'stats':
                    reply = 'stats - returns some stats'
                else:
                    reply = 'commands: search, ignore, unignore'
            elif command.lower() == 'search':
                reply = self.do_search(args, channel, user)
            elif command.lower() == 'ignore':
                reply = self.do_ignore(args or user)
            elif command.lower() == 'unignore':
                reply = self.do_unignore(args or user)
            else:
                reply = 'logger and searchbot - try "help"'

            if reply:
                self.msg(reply_to, reply)

    def do_search(self, query, channel, user):
        try:
            results = list(ESLogLine.objects.filter(query))
        except Exception as e:
            log.msg('ES Search Failed! - %s' % e)
            if 'SearchPhaseExecutionException' in str(e):
                return 'Invalid Query'
            else:
                return 'Something went wrong, please try again later'

        reply_to = channel
        if channel == self.nickname:
            reply_to = user

        # If small number of results, reply wherever
        if len(results) < 2:
            self.msg(reply_to, '%s results returned' % len(results))
            for result in results:
                self.msg(reply_to, "[%s] <%s> %s" % (str(result.time),
                                                     str(result.user),
                                                     str(result.message)))
        # if a large amount of results, reply in a PM
        elif (len(results) >= 2) and (len(results) < 10):
            self.msg(reply_to, '%s results returned' % len(results))
            for result in results:
                self.msg(user, "[%s] <%s> %s" % (str(result.time),
                                                 str(result.user),
                                                 str(result.message)))
        # if a *really* large amount of results, say no
        else:
            self.msg(reply_to, '%s results returned, narrow your search' % len(results))

    def do_ignore(self, args):
        self.writeLog(args, None, IGNORE_EVENT)
        if args in self.ignorelist:
            return "%s is already ignored, I can't ignore %s any harder!" % (args, args)
        else:
            self.ignorelist.append(args)
            return "I'm now ignoring %s" % args

    def do_unignore(self, args):
        self.writeLog(args, None, UNIGNORE_EVENT)
        if args in self.ignorelist:
            self.ignorelist.remove(args)
            return "I'm paying attention to %s now" % args
        else:
            return "I already wasn't ignoring %s" % args

    def action(self, user, channel, msg):
        """This will get called when the bot sees someone do an action."""
        #TODO: parse the acutal action out here
        user = user.split('!', 1)[0]
        self.writeLog(user, channel, msg, msg)

    # irc callbacks

    def irc_NICK(self, prefix, params):
        """Called when an IRC user changes their nickname."""
        old_nick = prefix.split('!')[0]
        new_nick = params[0]
        self.writeLog(old_nick, None, NICK_EVENT, new_nick)

    def ctcpQuery_ACTION(self, user, channel, data):
        user = user.split('!', 1)[0]
        self.writeLog(user, channel, CTCPQUERY_EVENT, data)

    def alterCollidedNick(self, nickname):
        return settings.ALT_NICK


class LogBotFactory(protocol.ClientFactory):

    def __init__(self):
        self.channels = settings.IRC_CHANNELS
        self.log_path = settings.LOG_FILE_PATH
        self.irc_host = settings.IRC_HOST

    def buildProtocol(self, addr):
        p = LogBot()
        p.factory = self
        return p

    def clientConnectionLost(self, connector, reason):
        print "connection failed:", reason
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        print "connection failed:", reason
        reactor.stop()
