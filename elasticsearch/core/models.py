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

from utils import DoesNotExist, MultipleObjectsReturned
from utils import parse_query

from utils import QueryStringQuery

from store import ElasticsearchClient
from queryset import ElasticsearchQueryset


class ElasticsearchUtils(object):
    """
    useful but scary methods not appropriate to be on the model/managers
    """
    _client = None
    _index = None
    _type = None

    def __init__(self, model_cls):
        self._client = model_cls._client
        self._index = model_cls._get_index()
        self._type = model_cls._get_doctype()

    def delete_index(self):
        return self._client.delete_index(self._index)

    def create_index(self):
        return self._client.create_index(self._index)

    def optimize(self):
        return self._client.optimize(self._index)

    def refresh(self):
        return self._client.refresh(self._index)

    def delete_all_documents(self):
        return self.delete_by_query("*:*")

    def delete_by_query(self, query):
        return self._client.delete_by_query(self._index, self._type, QueryStringQuery(query).to_json())


class ElasticsearchManager(object):
    """
    base manager class for elasticsearch documents
    """
    _model = None

    def _get_queryset(self, query):
        return ElasticsearchQueryset(self._model, query)

    def filter(self, query_string=None, **kwargs):
        return self._get_queryset(parse_query(query_string, **kwargs))

    # TODO: Allow getting documents directly by id, saving the query
    def get(self, query_string=None, **kwargs):
        qs = self._get_queryset(parse_query(query_string, **kwargs))
        if qs.count() > 1:
            raise MultipleObjectsReturned
        if qs.count() < 1:
            raise DoesNotExist
        return qs[0]

    def create(self, **kwargs):
        return self._model(**kwargs).save()

    def all(self):
        return self._get_queryset(parse_query('*:*'))


class ElasticsearchBaseModel(type):

    # triumph of metaprogramming </sarcasm>
    # this feels lame, but the only way I could figure out how to generically
    # define the base manager class to know what model it was for but not require an instance of
    # said model.
    def __getattribute__(mcs, name):

        # intercept the manager and populate it with the correct class
        if name == 'objects':
            objects = type.__getattribute__(mcs, name)
            objects._model = mcs
            return objects
        else:
            # otherwise, business as ususal
            return type.__getattribute__(mcs, name)


class ElasticsearchModel(object):
    """
    object representing an elasticsearch document.

    Works pretty much exactly like the django model/manager pattern
    except you don't specify attributes for the model because everything
    is all schemaless and shit.

    TODO: object mappings
    TODO: document validation
    TODO: document primary keys? (hardcoded to 'id')
    """
    __metaclass__ = ElasticsearchBaseModel

    _document = None

    _client = ElasticsearchClient()

    objects = ElasticsearchManager()

    def __init__(self, **kwargs):

        self._document = {}

        for k, v in kwargs.iteritems():
            self._document[k] = v

    def __setattr__(self, name, value):
        if name.startswith('_'):
            super(ElasticsearchModel, self).__setattr__(name, value)
        else:
            self._document[name] = value

    def __getattr__(self, name):
        try:
            return self._document.get(name)
        except KeyError:
            raise AttributeError

    def __str__(self):
        return 'instance at %s' % hex(id(self))

    def __repr__(self):
        return '<%s: %s>' % (self.__class__.__name__, self.__str__())

    def __dict__(self):
        return self._document

    @classmethod
    def _get_index(cls):
        return '%ss' % cls.__name__.lower()

    @classmethod
    def _get_doctype(cls):
        return cls.__name__.lower()

    def save(self):
        self._client.index(self._document, self._get_index(), self._get_doctype())
        return self
