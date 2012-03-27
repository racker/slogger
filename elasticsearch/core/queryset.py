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

from utils import Facet, build_query, parse_query


class ElasticsearchQueryset(object):
    """
    works a lot like django querysets in that they are lazily evaluated,
    you can slice, and you chain infinite .limit()s and .filter()s. You
    also use them just like django querysets - list(queryset) forces an
    evaluation and you can iterate over them.

    don't use this class directly

    TODO: The entire result is stored in RAM, we should probably be able to
          trade ram for more queries with some iterator magic
    TODO: This doesn't keep track of position in the results list, so if you
          slice a queryset after it's been evaluated it isn't smart enough to
          avoid a refresh even though it may have the results already cached
    TODO: Facets are kind of tangental to the inderactions with the documents,
          should this be fixed somehow?
    """

    def __init__(self, model, query=None):
        self._model = model
        self._client = model._client

        self._query = query
        if type(self._query) != list:
            self._query = [self._query]

        self._index = model._get_index()
        self._doctype = model._get_doctype()

        self._need_refresh = True

        # Initialize local state for Queryset
        self._raw_response = {}
        self._time_took = None
        self._timed_out = False
        self._results = []
        self._facets = None
        self._faceted_on = []
        self._total_results = None
        self._order_by = None

        self._size = 100
        self._offset = 0  # start at the beginning by default

    def __list__(self):
        """
        forces query evaluation
        """
        return self.results

    def __iter__(self):
        """
        forces query evaluation
        """
        #FIXME: we should make a way to iterate over a queryset but not load the entire
        #result into ram
        for v in self.__list__():
            yield v

    def __repr__(self):
        return str(self.__list__())

    def __getitem__(self, index):

        # sanitycheck straight from django queryset
        if not isinstance(index, (slice, int, long)):
            raise TypeError
        assert ((not isinstance(index, slice) and (index >= 0))
                or (isinstance(index, slice) and (index.start is None or index.start >= 0)
                and (index.stop is None or index.stop >= 0))), "Negative indexing is not supported."

        self._need_refresh = True

        if type(index) == slice:
            if index.start:
                self._offset = index.start
            if index.stop:
                self._size = index.stop - self._offset
            return self
        else:
            # evaluate the queryset if needed and try to index the result
            # list, throw if out of range

            # TODO: need_refresh being set to true above means that refresh
            # will always be needed

            return self.results[index]

    def _parse_facets(self, response):
        """
        helper that parses out facets from raw responses

        @param: response - raw elasticsearch search response
        @returns: dict - parsed document like so - {'tag': [('agent', 3), ('db', 1)], 'provider_type': [(5, 4)]}
        """
        facets = {}
        for k, v in response.get('facets', {}).iteritems():
            fl = []
            for facet in v['terms']:
                fl.append((facet['term'], facet['count']))
            facets[k] = fl
        return facets

    def _parse_results(self, response):
        """
        helper that parses out results from raw responses

        @param: response - raw elasticsearch search response
        @returns: list of documents
        """
        self._total_results = response.get('hits', {}).get('total', 0)

        results = []
        if self._total_results:
            for hit in response['hits']['hits']:
                results.append(self._model(**hit['_source']))
        return results

    def _parse_raw_response(self, response):
        """
        parse out results from raw responses and set up class private vars

        @param: response - raw elasticsearch search response
        @returns: None
        """
        self._raw_response = response

        # some stats
        self._time_took = response.get('took')
        self._timed_out = response.get('timed_out')

        # parse out the list of results
        self._results = self._parse_results(response)

        # parse out any facets
        self._facets = self._parse_facets(response)

        self._need_refresh = False

    def _refresh(self):
        """
        evaluates the current query and updates class vars
        """
        query = build_query(self._query, facets=self._faceted_on)
        response = self._client.search(self._index, self._doctype, query, order_by=self._order_by, size=self._size, offset=self._offset)
        self._parse_raw_response(response)

    def filter(self, query_string=None, **kwargs):
        queries = parse_query(query_string, **kwargs)
        self._query.extend(queries)
        self._need_refresh = True
        return self

    def order_by(self, order_by):
        """
        sorts the current query

        @param: order_by - string - field name. Sorts by ascending by default, prepend a '-' to sort by descending
        """
        order = 'asc'

        if order_by[0] == '-':
            order = 'desc'
            order_by = order_by[1:]

        self._order_by = '%s:%s' % (order_by, order)
        self._need_refresh = True

        return self

    def facet(self, facet):
        """
        adds a facet

        @param: facet - Facet object or list of objects
        @returns: ElasticsearchQueryset - self
        """
        if facet and type(facet) != list:
            facet = [facet]

        for f in facet:
            self._faceted_on.append(Facet(str(f)))

        return self

    def limit(self, limit):
        """
        limits the size of the queryset

        @param: query - ElasticsearchQuery-derived object or list of objects
        @returns: ElasticsearchFilter - self
        """
        self._size = limit
        return self

    def count(self):
        """
        returns current total size of the queryset

        @returns: int - number of results

        TODO: use the count api
        """
        if self._need_refresh:
            self._refresh()
        return int(len(self._results))

    @property
    def results(self):
        """
        evaluates the query if needed and returns results
        @returns: list of documents
        """
        if self._need_refresh:
            self._refresh()
        return self._results

    @property
    def facets(self):
        """
        evaluates the query if needed and returns facets
        @returns: dict of facets like so {'tag': [('agent', 3), ('db', 1)], 'provider_type': [(5, 4)]}
        """
        if self._need_refresh:
            self._refresh()
        return self._facets
