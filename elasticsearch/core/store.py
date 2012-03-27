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
Elasticsearch connection class and bare API implementation
"""
import random
import httplib
import urllib

import sys
import traceback

import json

from utils import NoNodesLeft, ElasticsearchException

import settings


class ElasticsearchConnection(object):
    """
    Simple wrapper around httplib.HTTPConnection that does a couple things

    * supports multiple hosts, and will try a request against them all before
      ultimately failing
    * calls getresponse() and read() and returns the raw response
    """

    _cluster = []
    _current_node = None
    _timeout = None
    _debug = False

    def __init__(self, cluster, timeout=None, debug=False):
        if not cluster or type(cluster) != list:
            raise ValueError('cluster must be a list with at least one server')

        self._cluster = cluster
        # Pick a random node in the cluster to try first
        self._current_node = random.randint(0, len(self._cluster))
        self._timeout = timeout
        self._debug = debug

    def get_traceback(self, exception):
        """
        Returns formatted traceback from a sys.exc_info()
        """
        return ''.join(traceback.format_exception(*exception))

    def _get_node(self):
        """
        Returns the current node from the cluster
        """
        next_node = self._current_node % len(self._cluster)
        self._current_node += 1
        return self._cluster[next_node]

    def _validate_response(self, response):
        if response.get('error'):
            raise ElasticsearchException(response.get('error').encode('ascii', 'ignore') or 'Unknown Error')

    def _request(self, *args, **kwargs):
        """
        Iterates over all clients in the cluster and tries to make a request
        """
        last_exception = None

        for i in range(len(self._cluster)):

            # print out the last exception if needed
            if self._debug and last_exception:
                print self.get_traceback(last_exception)

            try:
                node = self._get_node()
                conn = httplib.HTTPConnection(node, timeout=self._timeout)

                if self._debug:
                    conn.set_debuglevel(1)
                    print 'host: %s' % (node)

                conn.request(*args, **kwargs)
                res = conn.getresponse()
                res = res.read()
                conn.close()

                if self._debug:
                    print 'response: %s' % (res)

            except Exception:  # we've thrown an exception while fetching a response, so we record it and try another node
                last_exception = sys.exc_info()
                continue

            else:  # we got a response, so we load it, validate, and return or throw
                res = json.loads(res)
                self._validate_response(res)
                return res

        raise NoNodesLeft("Tried %s nodes, all failed. Last Exception: \n\n%s" % (len(self._cluster), self.get_traceback(last_exception)))

    def request(self, *args, **kwargs):
        response = self._request(*args, **kwargs)
        return response


class ElasticsearchClient(object):
    """
    Minimum-Viable elasticsearch python client
    """
    _connection = None  # ElasticsearchConnection
    _debug = False

    def __init__(self):
        self._debug = settings.DEBUG
        self._connection = ElasticsearchConnection(settings.ELASTICSEARCH_HOSTS,
                                                   timeout=settings.ELASTICSEARCH_TIMEOUT,
                                                   debug=self._debug)

    def _request(self, method, url, params=None, body=None, headers=None):
        """
        makes an actual request to elasticsearch

        @param: method - HTTP method ('GET', 'POST', etc)
        @param: url - URL path ('/myindex/mytype/_search')
        @param: params - dict of url parameters ({'pretty': 'true'})
        @param: body - data to send as the body of the request
        @param: headers - dict of HTTP headers

        @returns: dict, loaded json response
        """
        if not params:
            params = {}

        if not headers:
            headers = {}

        if self._debug:
            params['pretty'] = 'true'

        if params:
            url = '%s?%s' % (url, urllib.urlencode(params))

        response = self._connection.request(method, url, body, headers)
        return response

    def search(self, index, doctype, query, order_by=None, size=None, offset=None):
        """
        returns the raw search response from ES, don't use this directly

        @param: index - index name
        @param: doctype - type of the document
        @param: query - JSON
        @param: order_by - string - field name. Sorts by ascending by default, prepend a '-' to sort by descending
        @param: size - max amount of documents returned
        @param: offset - which document to start returning results from


        @returns: dict, loaded json response
        """

        params = {}
        if size:
            params['size'] = size
        if offset:
            params['from'] = offset
        if order_by:
            params['sort'] = order_by

        url = '/%s/%s/_search' % (index, doctype)

        response = self._request('GET', url, body=query, params=params)
        return response

    def get(self, index, doctype, docid):
        """
        gets a document by id

        @param: index - index name
        @param: doctype - type of the document
        @param: docid - integer - the id of the document

        @returns: dict - JSON loaded response
        """

        url = '/%s/%s/%s' % (index, doctype, docid)
        response = self._request('GET', url)
        return response

    def optimize(self, index=None):
        """
        optimizes an index

        @param: index - string - the name of the index

        @returns: dict - JSON loaded response
        """

        if index:
            url = '/%s/_optimize' % (index)
        else:
            url = '/_optimize'

        response = self._request('POST', url)
        return response

    def refresh(self, index=None):
        """
        refreshes an index

        @param: index - string - the name of the index

        @returns: dict - JSON loaded response
        """

        if index:
            url = '/%s/_refresh' % (index)
        else:
            url = '/_refresh'

        response = self._request('POST', url)
        return response

    def delete_by_id(self, index, doctype, docid):
        """
        deletes a document by id

        @param: index - index name
        @param: doctype - type of the document
        @param: docid - integer - the id of the document

        @returns: dict - JSON loaded response
        """

        url = '/%s/%s/%s' % (index, doctype, docid)
        response = self._request('DELETE', url)
        return response

    def delete_by_query(self, index, doctype, query):
        """
        deletes all documents by query

        @param: index - index name
        @param: doctype - type of the document
        @param: query - JSON query

        @returns: dict - JSON loaded response
        """

        url = '/%s/%s/_query' % (index, doctype)
        response = self._request('DELETE', url, body=query)
        return response

    def create_index(self, index, mapping=None):
        """
        creates given index

        @param: index - index name
        @param: mapping - JSON string or JSON-serializable dict - document mapping

        @returns: dict - JSON loaded response
        """
        if type(mapping) == dict:
            mapping = json.dumps(mapping)

        url = '%s' % (index)
        response = self._request('PUT', url, body=mapping)
        return response

    def delete_index(self, index):
        """
        creates given index

        @param: index - index name

        @returns: dict - JSON loaded response
        """
        url = '%s' % (index)
        response = self._request('DELETE', url)
        return response

    def index(self, doc, index, doctype, docid=None, parent=None):
        """
        indexes given document

        @param: doc - JSON string or JSON serializable dictionary - the document to be indexed
        @param: index - index name
        @param: doctype - type of the document
        @param: docid - integer - the id of the document
        @param: parent - integer - the id of the parent document

        @returns: Boolean depending on success of index
        """

        if type(doc) == dict:
            doc = json.dumps(doc)

        # url is /index/doctype/(optional docid)
        url = '/%s/%s' % (index, doctype)
        if docid:
            url += '/%s' % (docid)
            request_type = 'PUT'
        else:
            url += '/'
            request_type = 'POST'

        response = self._request(request_type, url, body=doc)
        return response
