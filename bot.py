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
import urllib

from twisted.words.protocols import irc
from twisted.internet import threads, reactor, protocol
from twisted.python import log, filepath

import settings
import loggers
from elasticsearch import ESLogLine
from elasticsearch.core import utils


class LogBot(irc.IRCClient):

    nickname = settings.NICK[:16]
    ignorelist = [nick[:16] for nick in settings.IGNORED_USERS]
    _user_left_FP = None

    def writeLog(self, message, user, channel):
        current_time = time.time()
        msg = (current_time, message, user, channel)
        for logger in self.loggers:
            logger.log(*msg)

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        self.loggers = [
            loggers.PyLogger(),
            loggers.BufferedMultiChannelFileLogger(
                self.factory.log_path, self.factory.channels),
            loggers.BufferedSearchLogger()]

        self.writeLog('CONNECTION ESTABLISHED', 'SYSTEM', 'SYSTEM_LOG')

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self, reason)
        self.writeLog('CONNECTION LOST: %s' % reason, 'SYSTEM', 'SYSTEM_LOG')

    def signedOn(self):
        """Called when bot has succesfully signed on to server."""
        self.setNick(self._attemptedNick)
        for channel_name in self.factory.channels:
            self.join(channel_name)

    def joined(self, channel):
        """This will get called when the bot joins the channel."""
        self.writeLog('JOINED CHANNEL (%s)' % channel, 'SYSTEM', 'SYSTEM_LOG')

    def privmsg(self, user, channel, msg):
        """This will get called when the bot receives a message."""
        user = user.split('!', 1)[0]

        if (channel == self.nickname) or (user in self.ignorelist) or (msg.startswith(self.nickname + ":")):
            current_time = time.time()
            log.msg(current_time, msg, user, channel)
        else:
            self.writeLog(msg, user, channel)

        if user not in self.ignorelist:
            if channel == self.nickname:  # private message
                self.handle_command(user, channel, msg)
            else:
                self.msg(
                    channel, "%s: I only answer private messages" % (user,))

    def userJoined(self, user, channel):
        """
        When the user joins a channel, log the join
        """
        self.writeLog('%s joined the channel.' % user, None, channel)
        # TODO: this is temporary
        if not self._user_is_self(user):
            self._pm_user_with_last_left(user, channel)

    def userLeft(self, user, channel):
        """
        When the user leaves a channel, log the leave
        """
        self.writeLog('%s left the channel.' % user, None, channel)
        # don't care about the result
        if user != self.nickname:
            self._record_user_last_exit_time(user, channel)

    # Ugliness

    def _pm_user_with_last_left(self, user, channel):
        """
        Private messages the user with the last time they left the channel,
        what messages were directed at them since then, and a url with history.

        TODO: file access should be asynchronous, and also don't build
        raw queries

        @param user: username
        @type user: C{str}

        @param user: channel name
        @type user: C{str}
        """
        last_exit_dict = self._get_user_last_exit_time(user, channel)
        last_exit_time = last_exit_dict.get(channel, None)

        def message_the_user(substrs, user, from_time):
            result = ["The last time you left this %s was: %s." % (
                channel, time.asctime(time.localtime(from_time)))]
            result.extend(substrs)
            result.append("History since you left here: %s" % (
                    'this is not ready yet'))
            self.msg(user, '\n'.join(result))

        def getQueryset(from_time, username, channel_name):
            return ESLogLine.objects._get_queryset([
                utils.RawQuery({
                    "query": {
                        "term": {"channel": channel_name.lstrip('#')}  # NOOOOOOOO
                    }
                }),
                utils.RawQuery({
                    "range": {
                        "time": {
                            "from": from_time,
                            "to": time.time()
                        }
                    }
                })
            ]).filter(username)

        def buildSubstr(queryset, from_time, username, channel_name):
            num = queryset.count()
            result = ["You were mentioned in %d new messages." % (num,)]

            if num > 5:
                result.append(
                    'There are too many to display here.  Please check the '
                    'history.')
                return result

            for query in queryset:
                result.append('  [%s] <%s> %s' % (
                    time.asctime(time.localtime(query.time)),
                    str(query.user),
                    str(query.message)))
            return result

        d = threads.deferToThread(getQueryset, last_exit_time, user, channel)
        d.addCallback(buildSubstr, last_exit_time, user, channel)
        d.addCallback(message_the_user, user, last_exit_time)

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

    def _record_user_last_exit_time(self, user, channel):
        """
        Record the current time for the user leaving the channel.  This is
        horrible and should probably be elsewhere.  Also, async.

        @param user: the username of the user
        @type user: C{str}

        @param channel: the channel that we want to record the last exit time
            for.
        @type channel: C{str}
        """

        # This is horrible.  Put this info somewhere else.
        if not self._user_left_FP:
            self._user_left_FP = filepath.FilePath('.lastexit')
            if not self._user_left_FP.exists():
                self._user_left_FP.createDirectory()

        # touch the file - the last time they exited will be the modification
        # time of the file
        self._user_left_FP.child('%s.%s' % (channel, user)).touch()

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
        if not self._user_left_FP:
            return results

        search_pattern = "%s.%s" % (channel or '*', user)
        matching_files = self._user_left_FP.globChildren(search_pattern)

        for child in matching_files:
            # the channel name is the filename minus ".username"
            channel_name = child.basename()[:-(len(user) + 1)]
            results[channel_name] = child.getModificationTime()

        return results

    # Commands

    def handle_command(self, user, channel, msg):

        log.msg('handling command')
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
                elif args == 'messages':
                    reply == ('messages <channel> - gets a list of messages '
                              'that were sent to you since the last time you '
                              'exited the channel')
                else:
                    reply = 'commands: search, ignore, unignore, messages'
            elif command.lower() == 'search':
                reply = self.do_search(args, channel, user)
            elif command.lower() == 'ignore':
                reply = self.do_ignore(args or user)
            elif command.lower() == 'unignore':
                reply = self.do_unignore(args or user)
            elif command.lower() == 'messages':
                self._pm_user_with_last_left(user, args)
                reply = None
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
        if args in self.ignorelist:
            return "%s is already ignored, I can't ignore %s any harder!" % (args, args)
        else:
            self.ignorelist.append(args)
            return "I'm now ignoring %s" % args

    def do_unignore(self, args):
        if args in self.ignorelist:
            self.ignorelist.remove(args)
            return "I'm paying attention to %s now" % args
        else:
            return "I already wasn't ignoring %s" % args

    def action(self, user, channel, msg):
        """This will get called when the bot sees someone do an action."""
        user = user.split('!', 1)[0]
        self.writeLog(msg, user, channel)

    # irc callbacks

    def irc_NICK(self, prefix, params):
        """Called when an IRC user changes their nickname."""
        old_nick = prefix.split('!')[0]
        new_nick = params[0]
        self.writeLog("%s CHANGED NICK TO %s" % (old_nick, new_nick), 'SYSTEM', 'SYSTEM_LOG')

    def ctcpQuery_ACTION(self, user, channel, data):
        user = user.split('!', 1)[0]
        self.writeLog("* %s %s" % (user, data), user, channel)

    def alterCollidedNick(self, nickname):
        return settings.ALT_NICK


class LogBotFactory(protocol.ClientFactory):

    def __init__(self):
        self.channels = settings.IRC_CHANNELS
        self.log_path = settings.LOG_FILE_PATH

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
