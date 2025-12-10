import os

import rocksdb

conn = None
def get_conn():
    global conn
    if conn:
        return conn

    if not os.path.exists('states'):
        os.makedirs('states')
    conn = rocksdb.DB('states/indexer.db', rocksdb.Options(create_if_missing=True))
    return conn

conn_tx = None
def get_conn_tx():
    global conn_tx
    if conn_tx:
        return conn_tx

    if not os.path.exists('states'):
        os.makedirs('states')
    conn_tx = rocksdb.DB('states/tx.db', rocksdb.Options(create_if_missing=True))
    return conn_tx

# os.removedirs('/dev/shm/tempspace.db')
# temp_conn = None
# def get_temp_conn():
#     global temp_conn
#     if temp_conn:
#         return temp_conn

#     temp_conn = rocksdb.DB('states/tempspace.db', rocksdb.Options(create_if_missing=True))
#     return temp_conn
