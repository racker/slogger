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

# -*- test-case-name: slogger.test.test_search -*-

from cStringIO import StringIO
import json

from twisted.internet import defer, protocol, reactor, task
from twisted.web.client import Agent, FileBodyProducer, ResponseDone
from twisted.web.iweb import IBodyProducer, UNKNOWN_LENGTH

from zope.interface import implements


class ESError(Exception):
    pass


class AsyncJSONProducer:
    """
    From: http://as.ynchrono.us/2010/06/asynchronous-json_18.html and the
    docs from L{twisted.web.client.FileBodyProducer}

    In case the json produced is so large that encoding it blocks the reactor
    doing the encoding, L{AsyncJSONProducer} can be used instead of, for
    example, a L{twisted.web.client.FileBodyProducer} that serves up a
    L{StringIO}.

    Uses a cooperator to iteratively encode JSON
    """
    implements(IBodyProducer)

    # do not know how many bytes the value will be json-encoded to
    length = UNKNOWN_LENGTH

    def __init__(self, value):
        self._value = value

    def startProducing(self, consumer):
        """
        Start a cooperative task which will encode bytes from the value and
        write them to C{consumer}.  Return a L{Deferred} which fires after
        the value has completely been encoded and all the resultant bytes have
        been written.
        """
        self._consumer = consumer
        self._iterable = json.JSONEncoder().iterencode(self._value)
        self._task = task.cooperate(self._produce())
        self._consumer.registerProducer(self, True)

        def maybeStopped(reason):
            # IBodyProducer.startProducing's Deferred isn't support to fire if
            # stopProducing is called.
            reason.trap(task.TaskStopped)
            return defer.Deferred()

        d = self._task.whenDone()
        d.addCallbacks(lambda ignored: None, maybeStopped)
        return d

    def pauseProducing(self):
        """
        Temporarily suspend copying bytes from the input file to the consumer
        by pausing the L{CooperativeTask} which drives that activity.
        """
        self._task.pause()

    def resumeProducing(self):
        """
        Undo the effects of a previous C{pauseProducing} and resume copying
        bytes to the consumer by resuming the L{CooperativeTask} which drives
        the write activity.
        """
        self._task.resume()

    def stopProducing(self):
        self._task.stop()

    def _produce(self):
        for chunk in self._iterable:
            self._consumer.write(chunk)
            yield None


class ESAgent(object):
    """
    A L{twisted.web.client.Agent} wrapper which handles elastic search queries.

    It takes a list of hosts, and every time a request is issues it tries all
    of those hosts before failing.  Every failure updates the list of hosts so
    that the next requests tries a different host first.

    @param agent: the agent to wrap
    @type agent: L{twisted.web.client.Agent}

    @param hosts: the lists of hosts to try
    @type hosts: C{list}

    @param requst_limit: the number of hosts to try before failing - defaults
        to trying every host in the list of hosts (<0 means try every host)
    @type hosts: C{int}
    """

    def __init__(self, agent, hosts, request_limit=None):
        self._agent = agent
        self._request_limit = request_limit
        if not request_limit or request_limit < 1:
            self._request_limit = len(hosts)

        # the number is just to figure out which are the best hosts to hit -
        # every time a connection to a host fails, the score gets decremented,
        # so in theory the best host to hit would be the one with the score of
        # 0
        self._hosts = dict([(host, 0) for host in hosts])

    def _make_body_producer(self, query):
        """
        Builds a body producer to be passed to L{_request} from a query

        @param query: the query to send
        @type query: C{dict}

        @return: a L{twisted.web.iweb.IBodyProducer} producing the json query
        """
        # dump JSON to a cStringIO
        file_like_object = StringIO()
        json.dump(query, file_like_object)
        # need to seek to 0 for the data be readable
        file_like_object.seek(0)
        # make a IBodyProducer that will produce the body of the request
        return FileBodyProducer(file_like_object)

    def _request_one_host(self, method, uri_subpath, body_producer,
                          hosts_to_try):
        """
        Makes a request to ES via http.

        @param method: the request method to send
        @type method: C{str}

        @param uri_subpath: e.g. /index/doctype/_search - must start with '/'
        @type uri_subpath: C{str}

        @param body_producer: a IBodyProducer that produces the json query
        @type body_producer: L{twisted.web.iweb.IBodyProducer}

        @param hosts_to_try: a list of hosts to try - This should be in the
            reverse order (last to first), simply because it is cheaper to
            pop one off the end.  Should never be empty.
        @type hosts: C{list}

        @return: a L{twisted.internet.defer.Deferred} that fires with the
            result of the request (a L{twisted.web.iweb.IResponse} provider),
            or fails if there is a problem setting up a connection over which
            to issue the request.
        """
        d = self._agent.request(
                method,
                '%s%s' % (hosts_to_try[-1], uri_subpath),
                None,
                body_producer)

        d.addErrback(self._request_failed_callback, method,
                     uri_subpath, body_producer, hosts_to_try)

        return d

    def _request_failed_callback(self, failure, method, uri_subpath,
                                 body_producer, hosts_to_try):
        """
        If a request to one host failed, up its failure counter and try the
        next another.  If no hosts are left, truly fail.

        @param failure: The failure that was errbacked - doesn't matter for now
        @type failure: L{twisted.python.failure.Failure}

        @param method: the request method to send - this will just be passed
            to the next requst
        @type method: C{str}

        @param uri_subpath: e.g. /index/doctype/_search - must start with '/'
            - this will just be passed to the next request
        @type uri_subpath: C{str}

        @param body_producer: a IBodyProducer that produces the json query -
            this will just be passed to the next request
        @type body_producer: L{twisted.web.iweb.IBodyProducer}

        @param hosts_to_try: the lists of hosts to try.  This should be in the
            reverse order (last to first), simply because it is cheaper to
            pop one off the end.  The current host being tried should be the
            last one in the list (and so hosts_to_try should never be empty)
        @type hosts_to_try: C{list}

        @return: the result of calling L{ESAgent._request_one_host} on another
            host, or fails if there are no more hosts
        """
        # failure.printTraceback()  # log it
        # pop off the last host, and decrease the score due to the failure
        self._hosts[hosts_to_try.pop(0)] -= 1

        # if there are more hosts to try, try the next one
        if len(hosts_to_try) > 0:
            return self._request_one_host(method, uri_subpath,
                                          body_producer, hosts_to_try)

        # fail if there are no more hosts to try again
        raise ESError("No elastic search hosts are responding.")

    def request(self, method, uri_subpath, query):
        """
        Makes a request to ES via http.

        @param method: the request method to send
        @type method: C{str}

        @param uri_subpath: e.g. /index/doctype/_search - must start with '/'
        @type uri_subpath: C{str}

        @param query: a json query to send to ES
        @type query: C{dict}

        @return: a L{twisted.internet.defer.Deferred} that fires with the
            result of the request (a L{twisted.web.iweb.IResponse} provider),
            or fails if there is a problem setting up a connection over which
            to issue the request.
        """

        # Build a list of hosts from the ones provided.  This should be in the
        # reverse order (last to first), simply because it is cheaper to pop
        # one off the end
        hosts_to_try = sorted(self._hosts,
                              key=(lambda host: self._hosts[host]))
        # make sure to try only so many
        hosts_to_try = hosts_to_try[:self._request_limit]

        return self._request_one_host(
            method, uri_subpath, FileBodyProducer(StringIO(query)), hosts_to_try)


class ESResponseProtocol(protocol.Protocol):
    """
    A protocol for receiving a response from ES
    """
    def __init__(self, deferred):
        """
        A deferred to call back when the response is finished and parsed.
        Calls back with a tuple containing the results, the facets, and the
        stats.
        """
        self._deferred = deferred
        self._data_store = StringIO()

    def dataReceived(self, bytes):
        """
        Write bytes to the file_like_object
        """
        self._data_store.write(bytes)

    def connectionLost(self, reason):
        # reason is actually a failure that wraps a ResponseDone exception, or
        # some other exception.  If it's not ResponseDone, errback that
        # exception.  Well, actually callback with that failure, so that the
        # stack trace isn't lost by re-wrapping that exception in another
        # failure
        if reason.check(ResponseDone):
            self._data_store.seek(0)  # for reading
            self._deferred.callback(self._data_store)
        else:
            self._deferred.callback(reason)


# --- the following methods are provided for utility

def _parse_facets(response):
    """
    Stolen code - needs attribution (morgabra)

    helper that parses out facets from raw responses

    @param: response - raw elasticsearch search response
    @returns: dict - parsed document like so -
        {'tag': [('agent', 3), ('db', 1)], 'provider_type': [(5, 4)]}
    """
    facets = {}
    for k, v in response.get('facets', {}).iteritems():
        fl = []
        for facet in v['terms']:
            fl.append((facet['term'], facet['count']))
        facets[k] = fl
    return facets


def _parse_results(response):
    """
    Stolen code - needs attribution (morgabra)

    helper that parses out results from raw responses

    @param: response - raw elasticsearch search response
    @returns: list of documents
    """
    total_results = response.get('hits', {}).get('total', 0)

    results = []
    if total_results:
        for hit in response['hits']['hits']:
            results.append(hit['_source'])
    return results


def parse_raw_response(raw_response_as_file):
    """
    Stolen code - needs attribution (morgabra)

    Parse out results, facets, and relevant statistics from a raw
    responses from the ES server. AFAIK, there is no way to incrementally
    parse JSON.  Some results can be huge, and decoding all the json may
    block the reactor.  Therefore, this should probably be called from a
    thread.

    Is probably threadsafe (?)

    @param raw_response_as_file - raw elasticsearch search response, as
        bytes, stored in a file like object
    @type raw_response_as_file: C{file}

    @returns: tuple of (results, facets, stats)
    """
    # load the response and decode the json
    response = json.load(raw_response_as_file)

    # some stats
    stats = {'time_took': response.get('took'),
             'timed_out': response.get('timed_out')}

    # parse out the list of results
    results = ESResponseProtocol._parse_results(response)

    # parse out any facets
    facets = ESResponseProtocol._parse_facets(response)

    return (results, facets, stats)


class SimpleESClient(object):
    """
    An extremely simple ES client that can search and index.

    @param hosts: a list of ES hosts to query
    @type hosts: C{list} of C{str}

    @param protocol: a protocol to use to receive the response - if none is
        provided, will use L{ESResponseProtocol} (yes this isn't a factory -
        fake)
    @type protocol: a L{IProtocol} provider
    """

    def __init__(self, hosts, protocol_factory=None):
        self._agent = ESAgent(Agent(reactor), hosts)
        self._protocol_factory = protocol_factory
        if not self._protocol_factory:
            self._protocol_factory = ESResponseProtocol

    def _handle_response(self, response):
        """
        Handle a response from L{Agent.request}

        @param response: response from agent
        @type response: L{IResponse} provider
        """
        finished = defer.Deferred()
        response.deliverBody(self._protocol_factory(finished))
        return finished

    def search(self, index, doctype, query):
        """
        Searches an index and doctype for a particular query

        @param index: the index to search
        @type index: C{str}

        @param doctype: the doctype to search
        @type doctype: C{str}

        @param query: the query to search
        @type query: C{dict}

        @returns: a L{twisted.internet.defer.Deferred} that fires with whatever
            the protocol returns, or fails if making a request to ES fails
        """
        d = self._agent.request('GET',
                                '/%s/%s/_search' % (index, doctype),
                                query)
        d.addCallback(self._handle_response)
        return d

    def create_index(self, *args, **kwargs):
        raise NotImplementedError

    def index(self, index, doctype, document, doc_id=None):
        """
        Indexes a document
        """
        method = "POST"
        if doc_id is not None:
            method = "PUT"

        uri = '/%s/%s/' % (index, doctype)
        if doc_id is not None:
            uri = '%s%s' % (uri, doc_id)

        d = self._agent.request(method, uri, document)
        d.addCallback(self._handle_response)
        return d

if __name__ == "__main__":
    a = SimpleESClient(['http://localhost:9200'])

    def pp(stuff):
        print stuff.read()

    def pf(failure):
        print 'here'
        failure.printTraceback()

    d = a.index('test', 'test', '{"user": "me", "message": "porkbun"}')
    d.addCallback(pp)
    d.addErrback(pf)
    d.addCallback(reactor.stop)

    from twisted.internet import reactor
    reactor.run()
