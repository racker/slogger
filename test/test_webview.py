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
Tests for L{web.view}
"""

import mock

from twisted.trial import unittest
from twisted.web.template import XMLString, flattenString

from elasticsearch import ESLogLine
from web import view

import settings


class FakeQueryItem(object):
    """
    Fake item that can in a fake queryset
    """
    def __init__(self, dictionary):
        for key, val in dictionary.iteritems():
            setattr(self, key, val)


class FakeQuerySet(list):
    facet = None
    facets = None


class BaseElementTestCase(unittest.TestCase):
    """
    Utilities for elements
    """
    # channel time username text
    message_xml = (
        '<t:transparent t:render="messages"><t:slot name="channel"/> '
        '<t:slot name="time"/> <t:slot name="username"/> '
        '<t:slot name="text"/>\n</t:transparent>')

    # channel_url channel_name
    channel_xml = (
        '<t:transparent t:render="channels"><t:slot name="channel_url"/> '
        '<t:slot name="channel_name"/>\n</t:transparent>')

    # XML produced should look like this (except without the nice indendation):
    #  <xml ...>
    #     ...
    #  <xml>
    def _get_XMLString(self, xml):
        """
        Takes internal XML, and wraps it with <xml> tags
        """
        wrapped = ('<xml xmlns:t="http://twistedmatrix.com/ns/'
            'twisted.web.template/0.1">\n%s\n</xml>' % (xml,))
        return XMLString(wrapped)

    def _cleanup_xml(self, xml):
        """
        Takes some xml (with <xml> tags), removes the wrapping <xml> tags, and
        returns whatever's inside, split up by line (ignores empty lines)
        """
        return filter(lambda item: item, xml.split('\n')[1:-1])

    def _get_check_equals_callback(self, expected):
        """
        Get a callback for testing equivalency - what is expected to be
        returned as a result, and what is actually returned

        Keep in mind that results is the xml after _cleanup_xml has been
        called on it.
        """
        return (lambda results: self.assertEqual(expected, results))

    def _run_test(self, element, test_callback, request=None):
        """
        Actually runs the test by flattening the string with the provided
        request, cleaning up the resultant XML, and then running test_callback
        on that result
        """
        if not request:
            request = mock.MagicMock(args={})
        d = flattenString(request, element)
        d.addCallback(self._cleanup_xml)
        d.addCallback(test_callback)
        return d


class FacetedMessageElementTestCase(BaseElementTestCase):
    """
    Tests for L{web.view.FacetedMessageElement}
    """

    def setUp(self):
        self.channels = ['#channel1', '#channel2']
        fakeFacets = {'channel': [(item, 5) for item in self.channels],
                      'user': [('you', 5)]}
        self.patch(FakeQuerySet, 'facet', mock.MagicMock(return_value=None))
        self.patch(FakeQuerySet, 'facets', fakeFacets)

    def test_render_channel(self):
        """
        Channel slots should be filled correctly
        """
        element = view.FacetedMessageElement(
            self._get_XMLString(self.channel_xml), FakeQuerySet())
        return self._run_test(element, self._get_check_equals_callback(
            # it should be &, for forms, but when filling a slot it gets
            # escaped to &amp;, which twisted's argument parser will parse
            # correctly
            ['/search?user=you&amp;channel=%23channel1 #channel1',
             '/search?user=you&amp;channel=%23channel2 #channel2']),
            mock.MagicMock(args={'user': ['you']}, prepath=["search"]))

    def test_render_users(self):
        """
        Channel slots should be filled correctly
        """
        xml = (  # user_url user_name
            '<t:transparent t:render="faceted_users">'
            '<t:slot name="user_url"/> <t:slot name="user_name"/>\n'
            '</t:transparent>')
        element = view.FacetedMessageElement(
            self._get_XMLString(xml), FakeQuerySet())
        return self._run_test(element, self._get_check_equals_callback(
            # it should be &, for forms, but when filling a slot it gets
            # escaped to &amp;, which twisted's argument parser will parse
            # correctly
            ['/search?user=you&amp;channel=chan you']),
            mock.MagicMock(args={'channel': ['chan']}, prepath=["search"]))

    def test_empty_messages(self):
        """
        If there are no messages, no messages should render
        """
        element = view.FacetedMessageElement(
            self._get_XMLString(self.message_xml), FakeQuerySet())
        return self._run_test(element, self._get_check_equals_callback([]))

    def test_fill_message_slots(self):
        """
        Message slots should be filled correctly
        """
        fakeSet = FakeQuerySet([
            FakeQueryItem({
                'channel': '#channel1',
                'user': 'me',
                'message': 'msg1',
                'time': 'yesterday'}),
            FakeQueryItem({
                'channel': '#channel2',
                'user': 'you',
                'message': 'msg2',
                'time': 'today'})
            ])
        element = view.FacetedMessageElement(
            self._get_XMLString(self.message_xml), fakeSet)
        return self._run_test(element, self._get_check_equals_callback(
            ['#channel1 yesterday me msg1', '#channel2 today you msg2']))


class NavElementTestCase(BaseElementTestCase):
    """
    Tests for L{web.view.NavElement}
    """

    def setUp(self):
        self.patch(settings, 'IRC_CHANNELS', ['#channel1', '#channel2'])

    def test_render_channel(self):
        """
        Channel slots should be filled correctly
        """
        element = view.NavElement(self._get_XMLString(self.channel_xml))
        return self._run_test(element, self._get_check_equals_callback(
            ['/?channel=%23channel1 #channel1',
             '/?channel=%23channel2 #channel2']))

    def test_render_home_is_active_class_should_be_active_if_on_root(self):
        """
        The class on this tag should be "active" if the url is '/'
        """
        element = view.NavElement(self._get_XMLString(
            '<tag t:render="home_is_active"><t:attr name="class">'
            '<t:slot name="active_or_not"/></t:attr></tag>'))
        return self._run_test(
            element,
            self._get_check_equals_callback(['<tag class="active"></tag>']),
            mock.MagicMock(prepath=['']))

    def test_render_home_is_active_class_should_be_empty_if_not_on_root(self):
        """
        The class on this tag should be "" if the url is not '/'
        """
        element = view.NavElement(self._get_XMLString(
            '<tag t:render="home_is_active"><t:attr name="class">'
            '<t:slot name="active_or_not"/></t:attr></tag>'))
        return self._run_test(
            element,
            self._get_check_equals_callback(['<tag class=""></tag>']),
            mock.MagicMock(prepath=['search']))


class IndexElementTestCase(BaseElementTestCase):
    """
    Tests for L{web.view.IndexElement}
    """

    def setUp(self):
        self.patch(view, 'NavElement', mock.MagicMock())

    def test_delegates_navbar_to_NavElement(self):
        """
        The navbar rendering should be delegated to the NavElement
        """
        element = view.IndexElement(
            self._get_XMLString('<div t:render="navbar"/>'))
        # fake render the navbar
        element.navbar(mock.MagicMock(), mock.MagicMock())
        self.assertEqual(1, view.NavElement.call_count)


class SearchResourceTestCase(unittest.TestCase):
    """
    Tests for L{web.view.SearchResource}

    L{view.SearchResource.render_GET} just flattens out a
    L{view.FacetedMessageElement}, so mainly test the argument processing
    """

    def setUp(self):
        self.patch(
            ESLogLine, 'objects', mock.MagicMock(spec=ESLogLine.objects))

    def test_no_args(self):
        """
        Without any arguments, no filtering at all should happen (call is made
        to L{ESLogLine.objects.all}, rather than L{ESLogLine.objects.filter})
        """
        view.SearchResource().element_from_request(mock.MagicMock())
        ESLogLine.objects.all.assert_called_once_with()
        self.assertFalse(ESLogLine.objects.filter.called)

    def test_empty_args(self):
        """
        Without empty arguments, no filtering at all should happen (call is
        made to L{ESLogLine.objects.all}, rather than
        L{ESLogLine.objects.filter})
        """
        view.SearchResource().element_from_request(
            mock.MagicMock(args={'channel': [], 'search': []}))
        ESLogLine.objects.all.assert_called_once_with()
        self.assertFalse(ESLogLine.objects.filter.called)

    def test_first_channel_arg(self):
        """
        With channel arguments, queryset should be filtered by the first
        channel (call is made to L{ESLogLine.objects.filter}, rather than
        L{ESLogLine.objects.filter})
        """
        view.SearchResource().element_from_request(
            mock.MagicMock(args={'channel': ['channel1', 'channel2']}))
        ESLogLine.objects.filter.assert_called_once_with(
            None, channel='channel1')
        self.assertFalse(ESLogLine.objects.all.called)

    def test_first_search_arg(self):
        """
        With search arguments, queryset should be filtered by the first
        search string (call is made to L{ESLogLine.objects.filter}, rather than
        L{ESLogLine.objects.filter})
        """
        view.SearchResource().element_from_request(mock.MagicMock(
            args={'search': ['searchstring1', 'searchstring2']}))
        ESLogLine.objects.filter.assert_called_once_with('searchstring1')
        self.assertFalse(ESLogLine.objects.all.called)
