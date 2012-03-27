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

# -*- test-case-name: slogger.test.test_webview -*-

import time
from datetime import date
import urllib

from twisted.web.resource import NoResource, Resource
from twisted.web.server import NOT_DONE_YET
from twisted.web.template import Element, renderer, flattenString, TagLoader

from elasticsearch import ESLogLine
from elasticsearch.core import utils
import settings
import templates


def _get_url_from_request(request, replacement_args=None):
    """
    Rebuilds a url from a request, with existing args replaced by args in
    replacement_args

    @param request: the http request object
    @type request: L{twisted.web.http.Request}

    @param replacement_args: which args to replace - this should be in the same
        form as the args in a L{twisted.web.http.Request} - that is,
        key=list of values
    @type replacement_args: C{dict}
    """
    # copy old arg dictionary
    newargs = {}
    if request and request.args:
        newargs = dict(request.args)

    if not replacement_args:
        replacement_args = {}

    # replace values, and check to make sure they're in the right form
    for key in replacement_args:
        if type(replacement_args[key]) == list:
            newargs[key] = replacement_args[key]
        elif type(replacement_args[key]) in (str, unicode):
            newargs[key] = [replacement_args[key]]

    return '/%s?%s' % (
        '/'.join(request.prepath), urllib.urlencode(newargs, True))


class ChannelList_Mixin(object):
    """
    Mixin to let Elements render channels
    """
    def get_channel_url(self, request, channel_name):
        """
        Convert channel name to a url
        """
        return _get_url_from_request(request, {'channel': [channel_name]})

    @renderer
    def channels(self, request, tag):
        """
        Renderer to render an ElasticsearchQueryset channel facet to the
        template
        """
        for channel_name in self._channels:
            yield tag.clone().fillSlots(
                channel_name=channel_name,
                channel_url=self.get_channel_url(request, channel_name))


class FacetedMessageElement(Element, ChannelList_Mixin):
    """
    Element that contains displays message information that is faceted

    @param loader: something to render data into, for example, a
        L{twisted.web.template.XMLFile)
    @type loader: L{twisted.web.iweb.ITemplateProvider}

    @param queryset: a queryset containing the information to display
    @type queryset: L{slogger.elasticsearch.queryset.ElasticsearchQueryset}
    """

    def __init__(self, loader, queryset):
        super(FacetedMessageElement, self).__init__(loader)
        self._queryset = queryset
        print 'results: %d' % (self._queryset.count(),)
        self._channels = []
        for item in self._queryset.facets.get('channel', []):
            # TODO: filter out system logs elsewhere
            channel_name = item[0]
            if channel_name != 'system_log':
                self._channels.append(channel_name)
        self._user_names = [
            item[0] for item in self._queryset.facets.get('user', [])]

    @renderer
    def messages(self, request, tag):
        """
        Renderer to render an ElasticsearchQueryset representing a set of irc
        messages to the template
        """
        for msg in self._queryset:
            # TODO: filter out system messages elsewhere
            if msg.channel.startswith('#'):
                yield tag.clone().fillSlots(
                    channel=msg.channel,
                    username=msg.user,
                    time=time.strftime('%m/%d/%Y %H:%M:%S',
                                       time.localtime(msg.time)),
                    text=msg.message)

    faceted_channels = ChannelList_Mixin.channels.im_func

    @renderer
    def faceted_users(self, request, tag):
        """
        Renderer to render an ElasticsearchQueryset channel user to the
        template
        """
        for name in self._user_names:
            yield tag.clone().fillSlots(
                user_name=name,
                user_url=_get_url_from_request(request, {'user': [name]}))


class NavElement(Element, ChannelList_Mixin):
    """
    Renders the nav bar of the UI

    @param loader: something to render data into, for example, a
        L{twisted.web.template.XMLFile)
    @type loader: L{twisted.web.iweb.ITemplateProvider}

    @param isHome: Whether 'home' should be active or not
    @type isHome: C{bool}
    """
    def __init__(self, loader, isHome=True):
        super(NavElement, self).__init__(loader)
        self._isHome = isHome
        self._channels = settings.IRC_CHANNELS

    @renderer
    def home_is_active(self, request, tag):
        activity = ''
        if request.prepath == ['']:
            activity = 'active'
        return tag.fillSlots(active_or_not=activity)

    chat_logs = ChannelList_Mixin.channels.im_func


class IndexElement(Element, ChannelList_Mixin):
    """
    Element representing the main page of Slogger
    """
    def __init__(self, loader, *args, **kwargs):
        """
        Takes args to pass to the creation of the container element
        """
        super(IndexElement, self).__init__(loader)
        self._args = args
        self._kwargs = kwargs

    @renderer
    def navbar(self, request, tag):
        return NavElement(TagLoader(tag))

    @renderer
    def container(self, request, tag):
        if request.prepath == ['search']:
            return FacetedMessageElement(
                templates.SEARCH_LOADER, *self._args, **self._kwargs)
        elif request.prepath == ['']:
            return FacetedMessageElement(
                templates.LOG_LOADER, *self._args, **self._kwargs)
        return tag


class BaseElementRendererResource(Resource):
    """
    Resource to render an element
    """
    def _finish_request(self, output, request):
        """
        Finishes writing the output to the request and terminates the request
        """
        if output:
            request.write(output)
        request.finish()

    def render_GET(self, request):
        """
        Renders self.element
        """
        request.write('<!DOCTYPE html>\n')
        d = flattenString(request, self.element_from_request(request))
        d.addCallback(self._finish_request, request)
        return NOT_DONE_YET

    def element_from_request(self, request):
        """
        Produces en element to be rendered
        """
        raise NotImplementedError


class LogsResource(BaseElementRendererResource):
    """
    Resource to display the Slogger flat file logs.  Expected arguments are:

    channel - which channel to display

    If more than one value is provided for either of these argument names, only
    the first one will be used.
    """

    def element_from_request(self, request):
        """
        """
        channel = request.args.get('channel', settings.IRC_CHANNELS)[0]
        _from = request.args.get('from', [None])[0]
        if not _from:
            # TODO: the midnight time should be cached
            _from = time.mktime(date.today().timetuple())
        _to = request.args.get('to', [None])[0]

        # this is pretty awful - but I don't know how to otherwise get a
        # range query
        queryset = ESLogLine.objects._get_queryset([
            utils.RawQuery({
                "query": {
                    "term": {"channel": channel.lstrip('#')}  # NOOOOOOOO
                }
            }),
            utils.RawQuery({
                "range": {
                    "time": {
                        "from": _from,
                        "to": _to
                    }
                }
            })
        ])

        return IndexElement(
            templates.INDEX_LOADER,
            queryset.facet('user').order_by('time'))


class SearchResource(BaseElementRendererResource):
    """
    Resource to display the Slogger search page.  Expected arguments are:

    channel - which channel to facet
    user - which user to facet
    search - a string to use to query the ES

    If more than one value is provided for either of these argument names, only
    the first one will be used.
    """

    def element_from_request(self, request):
        """
        Identify the desired arguments (search string and channel name) and
        query ES
        """
        kwargs = {}
        queryString = None

        search_args = request.args.get('search', [])
        channel_args = request.args.get('channel', [])
        user_args = request.args.get('user', [])

        if len(search_args) > 0:
            queryString = search_args[0]

        if len(channel_args) > 0:
            kwargs['channel'] = channel_args[0]

        if len(user_args) > 0:
            kwargs['user'] = user_args[0]

        if queryString or len(kwargs) > 0:
            queryset = ESLogLine.objects.filter(queryString, **kwargs)
        else:
            queryset = ESLogLine.objects.all()

        return IndexElement(
            templates.INDEX_LOADER,
            queryset.facet('channel').facet('user').order_by('time'))


class SloggerMainResource(Resource):
    def getChild(self, path, request):
        if path == '':
            return LogsResource()
        if path == 'search':
            return SearchResource()
        return NoResource()
