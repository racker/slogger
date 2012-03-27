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
utility classes and functions
"""
import json


class NoNodesLeft(Exception):
    pass


class DoesNotExist(Exception):
    pass


class MultipleObjectsReturned(Exception):
    pass


class ElasticsearchException(Exception):
    pass


class ElasticsearchQuery(object):
    """
    Abstract base class for the various Elasticsearch query types
    """
    _query = {}

    def __init__(self, *args, **kwargs):
        self._query = self._build_query(*args, **kwargs)

    def __str__(self):
        return '%s' % (self.to_json())

    def __repr__(self):
        return self.__str__()

    def __eq__(self, other):
        if self.__class__ == other.__class__:
            return str(other) == str(self)

        return False

    def _build_query(self, *args, **kwargs):
        """
        overload this and return a JSON-serializable dict
        """
        raise NotImplementedError

    def to_json(self):
        return json.dumps(self._query)

    def to_dict(self):
        return self._query


class RawQuery(ElasticsearchQuery):
    """
    takes any dict and runs it as a query, useful for debugging or one-offs
    """
    def _build_query(self, query):
        return query


class MatchAllQuery(ElasticsearchQuery):
    """
    matches all documents
    """
    def _build_query(self):
        return {"match_all": {}}


class TermQuery(ElasticsearchQuery):
    """
    http://www.elasticsearch.org/guide/reference/query-dsl/term-query.html

    Basic key/value query
    """
    def _build_query(self, term, value):
        return {'term': {term: value}}


class QueryStringQuery(ElasticsearchQuery):
    """
    http://www.elasticsearch.org/guide/reference/query-dsl/query-string-query.html

    Evaluates a querystring, basic lucene syntax
    """
    def _build_query(self, query_string):
        return {'query_string': {'query': str(query_string)}}


class FilteredQuery(ElasticsearchQuery):
    """
    http://www.elasticsearch.org/guide/reference/query-dsl/constant-score-query.html
    http://www.elasticsearch.org/guide/reference/query-dsl/and-filter.html

    A constant-scoring query that wraps a filter that ANDs the queries.
    """
    def _build_query(self, and_queries=None):
        if not and_queries or type(and_queries) != list:
            raise ValueError('and_queries should be a list with at least one query')

        queries = []
        for q in and_queries:
            # we have to wrap query_string queries
            if isinstance(q, QueryStringQuery):
                queries.append({'query': q.to_dict()})
            else:
                queries.append(q.to_dict())

        return {'constant_score': {'filter': {'and': queries}}}


class Facet(ElasticsearchQuery):
    """
    creates a facet, which is actually build into the search query a little
    differently.

    TODO: this probably shouldn't subclass ElasticsearchQuery as it's not actually
          a query
    """
    def _build_query(self, facet):
        return {facet: {'terms': {'field': facet}}}


def build_query(query, facets=None):
    """
    builds the current query into JSON suitable for use with the API
    TODO: This is pretty stupid. Should we actually implement anything more
          than querystring and term we should really think about how we want
          to represent and build queries.
    @returns: string - JSON suitable for searching
    """
    if not isinstance(query, RawQuery):
        # if we are given a list of queries we need to AND them together
        if query and type(query) == list:
            query = FilteredQuery(and_queries=query)

        if facets and type(facets) != list:
            facets = [facets]

        if query:
            query = {'query': query.to_dict()}
            if facets:
                query['facets'] = {}
                for facet in facets:
                    query['facets'].update(facet.to_dict())
        return json.dumps(query)


def parse_query(query_string=None, **kwargs):
    """
    @param: query_string - lucene query string for QueryStringQuery
    @param: **kwargs - key/value pairs to run in a TermQuery
    @returns: list - list of query objects
    """
    queries = []
    # special querystring attribute
    if query_string:
        queries.append(QueryStringQuery(query_string))
    # otherwise, straight-up term queries
    for k, v in kwargs.items():
        queries.append(TermQuery(k, v))
    return queries
