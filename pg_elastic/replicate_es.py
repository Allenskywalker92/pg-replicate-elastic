from __future__ import print_function
import sys
import json
import multiprocessing
from elasticsearch import Elasticsearch
from elasticsearch import helpers
from dateutil.parser import parse
from datetime import datetime

class ElasticRepliaction(object):
    """CRUD replication to Elasticsearch"""

    def __init__(self, tables, allow_delete=True, username=None, password=None, connection=None):
        self.db_tables = tables
        self.allow_delete = allow_delete
        self.exclude_columns = []
        if connection:
            print('ES connection to %s ...' % connection, file=sys.stderr)
            self.es = Elasticsearch(connection, http_auth=(username, password)) if username and password else Elasticsearch(connection)
        else:
            print('ES connection to http://localhost:9200/ ...', file=sys.stderr)
            self.es = Elasticsearch()

        print(self.es.info())
        self.table_ids = {}

        def init_values(table):
            self.table_ids[table['name'].strip()] = table['primary_key']

            if 'exclude_columns' in table:
                self.exclude_columns += table['exclude_columns'].split(',')
            # self.es.indices.create(index='tracking', ignore=400)

        map(init_values, tables)
        print('Creating index tracking', file=sys.stderr)
        self.es.indices.create('tracking', ignore=400)

    def handle_dates(self, document, column, value):
        try:
            document[column] = parse(value)
        except Exception as e:
            document[column] = value
        return document

    def parse_doc_body(self, document, change):
        data = {}
        for idx, column in enumerate(change['columnnames']):
            if column not in self.exclude_columns:
                if change['kind'] == 'update':
                    document = self.handle_dates(document, change['columnnames'][idx], change['columnvalues'][idx])
                    # document['_source'] = {}
                    # document['_source']['doc'] = self.handle_dates(data, change['columnnames'][idx], change['columnvalues'][idx])
                else:
                    document = self.handle_dates(document, change['columnnames'][idx], change['columnvalues'][idx])

        document['_original'] = ''
        document['_original'] = json.dumps(change)
        return document

    def parse_insert_or_update(self, document, change):
        if change['kind'] == 'update':
            document['_op_type'] = 'update'
        else:
            document['_op_type'] = 'create'
        document = self.parse_doc_body(document, change)
        return document

    def parse_delete(self, document, change):
        document['_op_type'] = 'delete'
        # for idx, column in enumerate(change['oldkeys']['keynames']):
        #     if column == document['_id']:
        #         document['_id'] = change['oldkeys']['keyvalues'][idx]
        #         if type(document['_id']) == str or type(document['_id']) == unicode:
        #             document['_id'] = document['_id'].strip()
        #         break

        document['_original'] = ''
        document['_original'] = json.dumps(change)
        return document

    def replicate(self, data, initial=False, initial_table=None):

        def initial_replicate(entry):
            document = {}
            document['_index'] = initial_table
            document['_type'] = 'document'
            document['_op_type'] = 'create'
            document['_id'] = entry[self.table_ids[initial_table]]
            entry = dict(entry)

            for key, value in entry.iteritems():
                if key not in self.exclude_columns and key != document['_id']:
                    document[key] = value
            return document

        def normal_replicate(change):
            kind = change['kind']
            table = change['table']
            
            if kind in ['delete', 'insert', 'update'] and table in self.table_ids.keys():
                document = {}
                document['table_name'] = table
                if kind == 'delete':
                    document = self.parse_delete(document, change)
                else:
                    document = self.parse_insert_or_update(document, change)

                document['index_time'] = datetime.utcnow()
                return self.es.index('tracking', doc_type = '_doc', body = document)

        if initial and initial_table:
            try:
                helpers.bulk(self.es, map(initial_replicate, data))
            except Exception as e:
                pass
        else:
            data_to_replicate = map(normal_replicate, data['change'])

            # for success, info in helpers.parallel_bulk(self.es, data_to_replicate, thread_count=multiprocessing.cpu_count(), chunk_size=40):
            #     if not success:
            #         print('A document failed:', info)
            #     else:
            #         print('success')

            print(data_to_replicate)