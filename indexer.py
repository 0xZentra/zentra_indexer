# from __future__ import print_function

import sys
# import os
# import time
# import uuid
# import tracemalloc
# import hashlib
import json
import binascii

# import tornado.options
import tornado.web
import tornado.ioloop
import tornado.httpserver
import tornado.gen
import tornado.escape

import setting
import database
import funcs
import space
from space import get
from space import put


global_state = database.get_conn()
# pending_state = database.get_temp_conn()
global_input = database.get_conn_tx()


class OrderbookAPIHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')

        base = self.get_argument('base').upper()
        quote = self.get_argument('quote').upper()
        space.info = {'chain': 'base'}

        buy_start = get('trade', f'{base}_{quote}_buy_start', 1)
        print(f'{base}_{quote}_buy_start')
        print('buy_start', buy_start)
        buys = []
        while True:
            buy = get('trade', f'{base}_{quote}_buy', [], str(buy_start))
            print('buy', buy)
            if not buy:
                break
            buys.append(buy)
            if buy[4] is None:
                break
            buy_start = buy[4]

        sell_start = get('trade', f'{base}_{quote}_sell_start', 1)
        print(f'{base}_{quote}_sell_start')
        print('sell_start', sell_start)
        sells = []
        while True:
            sell = get('trade', f'{base}_{quote}_sell', [], str(sell_start))
            print('sell', sell)
            if not sell:
                break
            sells.append(sell)
            if sell[4] is None:
                break
            sell_start = sell[4]

        self.finish({
            'buy_start': buy_start, 
            'buys': buys,
            'sell_start': sell_start, 
            'sells': sells
        })


class GetLatestStateAPIHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'GET, OPTIONS')

        global global_state
        prefix = self.get_argument('prefix')
        k = ('%s-' % prefix).encode('utf8')
        it = global_state.iteritems()
        it.seek(k)
        result = None
        for key, value_json in it:
            if not key.startswith(k):
                break
            result = json.loads(value_json)
            break
        self.finish({'result':result})


class QueryRecentStateAPIHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'GET, OPTIONS')

        global global_state
        prefix = self.get_argument('prefix')
        k = ('%s-' % prefix).encode('utf8')
        it = global_state.iteritems()
        it.seek(k)
        result = {}
        for key, value_json in it:
            if not key.startswith(k):
                break
            ks = key.decode('utf8').split('-')
            result[setting.REVERSED_NO - int(ks[3])] = json.loads(value_json)
        self.finish(result)


class BlocksHandler(tornado.web.RequestHandler):
    def get(self):
        global global_state
        global global_input
        self.chain = self.get_argument('chain', 'base')
        assert self.chain in setting.chains

        it = global_input.iteritems()
        it.seek(('%s-block-' % self.chain).encode('utf8'))
        self.recent_blocks = []
        c = 0
        for key, value_json in it:
            if not key.startswith(('%s-block-' % self.chain).encode('utf8')):
                break
            print('block1', key)
            # self.write('%s %s<br>' % (key, value_json))
            _, _, block_height, block_hash = key.decode('utf8').split('-')
            self.recent_blocks.append([setting.REVERSED_NO-int(block_height), block_hash])
            c += 1
            if c >= 20:
                break

        c = 0
        self.recent_transactions = []
        for _block_number, block_hash in self.recent_blocks:
            k = '%s-blocktx-%s-' % (self.chain, block_hash)
            it.seek(k.encode('utf8'))
            for key, value_json in it:
                if not key.startswith(k.encode('utf8')):
                    break
                print('block2', key)
                _, _, block_hash, tx_hash  = key.decode('utf8').split('-')
                self.recent_transactions.append([tx_hash, block_hash])
                c += 1
                if c >= 20:
                    break
            if c >= 20:
                break

        self.render('template/blocks.html')


class BlocksHandler(tornado.web.RequestHandler):
    def get(self):
        global global_state
        global global_input
        self.chain = self.get_argument('chain', 'base')
        assert self.chain in setting.chains

        it = global_input.iteritems()
        it.seek(('%s-block-' % self.chain).encode('utf8'))
        self.recent_blocks = []
        c = 0
        for key, value_json in it:
            if not key.startswith(('%s-block-' % self.chain).encode('utf8')):
                break
            print('block1', key)
            # self.write('%s %s<br>' % (key, value_json))
            _, _, block_height, block_hash = key.decode('utf8').split('-')
            self.recent_blocks.append([setting.REVERSED_NO-int(block_height), block_hash])
            c += 1
            if c >= 20:
                break

        c = 0
        self.recent_transactions = []
        for _block_number, block_hash in self.recent_blocks:
            k = '%s-blocktx-%s-' % (self.chain, block_hash)
            it.seek(k.encode('utf8'))
            for key, value_json in it:
                if not key.startswith(k.encode('utf8')):
                    break
                print('block2', key)
                _, _, block_hash, tx_hash  = key.decode('utf8').split('-')
                self.recent_transactions.append([tx_hash, block_hash])
                c += 1
                if c >= 20:
                    break
            if c >= 20:
                break

        self.render('template/blocks.html')


class BlockHandler(tornado.web.RequestHandler):
    def get(self):
        global global_state
        global global_input
        self.block_hash = self.get_argument('blockhash').replace('0x', '')
        it = global_input.iteritems()
        self.chain = self.get_argument('chain', 'base')
        assert self.chain in setting.chains

        it.seek(('%s-blocktx-%s-' % (self.chain, self.block_hash)).encode('utf8'))
        self.txs = []
        self.block_number = 0
        for key, value_json in it:
            print('blocktx', key)
            if not key.startswith(('%s-blocktx-%s-' % (self.chain, self.block_hash)).encode('utf8')):
                break
            # self.write('%s %s<br>' % (key, value_json))
            value = json.loads(value_json)
            self.block_number = value['block_number']
            _, _, _, tx_hash = key.decode('utf8').split('-')
            self.txs.append([tx_hash, value['tx_index']])

        self.render('template/block.html')


class TxHandler(tornado.web.RequestHandler):
    def get(self):
        tx_hash = self.get_argument('txhash').replace('0x', '')
        # print(tx_hash)
        # global global_state
        global global_input
        self.chain = self.get_argument('chain', 'base')
        assert self.chain in setting.chains

        it = global_input.iteritems()
        it.seek(('%s-tx-%s-' % (self.chain, tx_hash)).encode('utf8'))
        self.tx_hash = ''
        for key, value_json in it:
            print('tx', key, value_json)
            if not key.startswith(('%s-tx-%s-' % (self.chain, tx_hash)).encode('utf8')):
                break
            _, _, self.tx_hash, self.block_hash = key.decode('utf8').split('-')
            self.value_json = value_json

            # self.write('%s %s<br>' % (key, value_json))
            # self.txs.append([tx_hash, block_hash])

        it.seek(('%s-blocktx-%s-' % (self.chain, self.block_hash)).encode('utf8'))
        for key, value_json in it:
            print('blocktx', key)
            if not key.startswith(('%s-blocktx-%s-' % (self.chain, self.block_hash)).encode('utf8')):
                break
            # self.write('%s %s<br>' % (key, value_json))
            value = json.loads(value_json)
            self.block_number = value['block_number']
            self.tx_index = value['tx_index']
            self.sender = value.get('sender', '')
            break

        self.render('template/tx.html')


class GotoHandler(tornado.web.RequestHandler):
    def get(self):
        global global_state
        query = self.get_argument('query')
        if query.isdigit():
            blockno = int(query)
            it = global_input.iteritems()
            it.seek(('base-block-'.encode('utf8')))
            block_hash = None
            for key, value_json in it:
                if not key.startswith('base-block-'.encode('utf8')):
                    break
                ks = key.decode('utf8').split('-')
                if len(ks) < 4:
                    continue
                reversed_no = int(ks[2])
                if setting.REVERSED_NO - reversed_no == blockno:
                    block_hash = ks[3]
                    break
            if block_hash is None:
                self.finish('Error Block not found')
                return
            self.redirect(f'/block?blockhash={block_hash}')
            return

        if query.startswith('0x'):
            hex_query = query[2:]
        else:
            hex_query = query

        # Check if it's a block hash
        block_key = f'base-blocktx-{hex_query}-'.encode('utf8')
        it = global_input.iteritems()
        it.seek(block_key)
        for key, _ in it:
            if key.startswith(block_key):
                self.redirect(f'/block?blockhash={hex_query}')
                return
            break

        # Check if it's a tx hash
        tx_key = f'base-tx-{hex_query}-'.encode('utf8')
        it.seek(tx_key)
        for key, _ in it:
            if key.startswith(tx_key):
                self.redirect(f'/tx?txhash={hex_query}')
                return
            break

        self.finish('Error Not found')

class StateHandler(tornado.web.RequestHandler):
    def get(self):
        global global_state

        self.chain = self.get_argument('chain', 'base')
        try:
            self.block_number = int(self.get_argument('blockno'))
        except:
            self.block_number = int(global_input.get(('%s-height' % (self.chain)).encode('utf8')))

        self.state_keys = []
        self.state_values = {}
        for i in range(100):
            # no = (str(setting.REVERSED_NO - self.block_number)).zfill(16)
            # k = ('%s_state_key-%s-%s' % (self.chain, i, no)).encode('utf8')
            k = ('%s_state_key-%s-' % (self.chain, i)).encode('utf8')
            # print('k', k)

            it = global_state.iteritems()
            it.seek(k)
            for key, value_json in it:
                if not key.startswith(k):
                    break
                # print(key, k)
                ks = key.decode('utf8').split('-')
                no = setting.REVERSED_NO - int(ks[2])
                if no > self.block_number:
                    continue

                key2 = json.loads(value_json)
                self.state_keys.append(key2)

                it2 = global_state.iteritems()
                k2 = ('%s-%s-%s' % (self.chain, key2, ks[2])).encode('utf8')
                print('k2', k2)
                it2.seek(k2)
                for key, value_json in it2:
                    if not key.startswith(k2):
                        break
                    # print('k3', key, key2, no, value_json)
                    if key2 not in self.state_values:
                        self.state_values[key2] = no, value_json
                    break
                break

        # print('state_values', self.state_values)
        self.render('template/state.html')

class InputHandler(tornado.web.RequestHandler):
    def get(self):
        global global_state
        global global_input

        self.block_number = int(self.get_argument('blockno', 1))
        chain = self.get_argument('chain', 'base')
        height = self.block_number//10*10
        self.write('<a href="/input?chain=%s&blockno=%s">%s</a> ' % (chain, height - 10, height - 10))
        self.write('<a href="/input?chain=%s&blockno=%s">%s</a><br><br>' % (chain, height + 10, height + 10))

        it = global_input.iteritems()
        it1 = global_input.iteritems()
        for i in range(height, height+10):
            self.write('%s<br>' % i)
            reversed_height = str(setting.REVERSED_NO - i).zfill(16)
            k = ('%s-block-%s-' % (chain, reversed_height)).encode('utf8')
            it.seek(k)
            # self.txs = []
            for key, value_json in it:
                print('block', key)
                if not key.startswith(k):
                    break

                self.write('%s %s<br>' % (key, value_json))
                # _, _, tx_hash, block_hash = key.decode('utf8').split('-')
                # self.txs.append([tx_hash, block_hash])
                tx_hashes = json.loads(value_json).get('transactions', [])
                for tx_hash in tx_hashes:
                    self.write('%s<br>' % (tx_hash))
                    # it1.seek_to_first()
                    # print(1, ('%s-tx-%s' % (chain, tx_hash) ).encode('utf8'))
                    k = ('%s-tx-%s' % (chain, tx_hash) ).encode('utf8')
                    it1.seek(k)
                    for key1, value_json1 in it1:
                        print('key1', key1)
                        if not key1.startswith(k):
                            break
                        _, _, _, block_hash = key1.decode('utf8').split('-')
                        self.write('%s<br>' % (value_json1))

                    k = ('%s-blocktx-%s' % (chain, block_hash) ).encode('utf8')
                    it1.seek(k)
                    for key2, value_json2 in it1:
                        print('key2', key2)
                        if not key2.startswith(k):
                            break
                        self.write('%s<br>' % (value_json2))

        self.write('<br>')
        k = ('%s-height' % chain).encode('utf8')
        # it.seek_to_first()
        it.seek(k)
        # self.txs = []
        for key, value_json in it:
            # print(key)
            if not key.startswith(k):
                break

            self.write('%s %s<br>' % (key, value_json))

        # self.render('template/tx.html')
        self.finish()

class HeightHandler(tornado.web.RequestHandler):
    def get(self):
        global global_state
        global global_input

        chain = self.get_argument('chain')
        # it = global_input.iteritems()
        height = global_input.get(('%s-height' % (chain)).encode('utf8'))
        if height:
            height = int(height.decode('utf8'))
        self.finish({'chain': chain, 'height': height})

class EntryHandler(tornado.web.RequestHandler):
    def get(self):
        global global_state

        addr = self.get_argument('addr')
        if addr.lower() == setting.account.address.lower():
            self.finish({'entry': True, 'handle': setting.handle, 'credit': 10**18})
        elif addr.lower() == setting.account2.address.lower():
            self.finish({'entry': True, 'handle': setting.handle2, 'credit': 10**18})
        else:
            handle = global_state.get(('op-handle-addr2handle:%s' % (addr.lower())).encode('utf8'))
            # if handle:
            #     height = int(height.decode('utf8'))
            self.finish({'entry': True, 'handle': handle.decode('utf8'), 'credit': 10**18})

class GetBlockAPIHandler(tornado.web.RequestHandler):
    def get(self):
        global global_state
        global global_input
        number = int(self.get_argument('number', 0))
        chain = self.get_argument('chain', 'base')
        assert chain in setting.chains

        it = global_input.iteritems()
        reversed_height = str(setting.REVERSED_NO - number).zfill(16)
        k = '%s-block-%s-' % (chain, reversed_height)
        it.seek(k.encode('utf8'))
        for key, value_json in it:
            if not key.startswith(k.encode('utf8')):
                break
            print('block', key, value_json)
            value = json.loads(value_json)
            # for i in value['transactions']:
            #     print('tx', i)
            self.finish(value)
            break


class GetTxAPIHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'GET, OPTIONS')

        global global_state
        global global_input
        tx_hash = self.get_argument('txhash')
        chain = self.get_argument('chain', 'base')
        assert chain in setting.chains

        block_hash = None
        it = global_input.iteritems()
        k = '%s-tx-%s-' % (chain, tx_hash)
        it.seek(k.encode('utf8'))
        for key, value_json in it:
            if not key.startswith(k.encode('utf8')):
                break
            print('block', key, value_json)
            _, _, _, block_hash = key.decode('utf8').split('-')
            tx_value = json.loads(value_json)
            # for i in value['transactions']:
            #     print('tx', i)
            print(tx_value)
            break

        if block_hash is None:
            self.finish({'error': 'transaction not found yet'})
            return

        k = '%s-blocktx-%s-' % (chain, block_hash)
        it.seek(k.encode('utf8'))
        for key, value_json in it:
            if not key.startswith(k.encode('utf8')):
                break
            print('block', key, value_json)
            tx_info = json.loads(value_json)
            # for i in value['transactions']:
            #     print('tx', i)
            print(tx_info)
            break
        self.finish({'value': tx_value, 'info': tx_info, 'error': None})


class MainHandler(tornado.web.RequestHandler):
    def get(self):
        if self.request.remote_ip != '127.0.0.1':
            self.finish('not allowed')
        else:
            self.redirect('/blocks')

    def post(self):
        if self.request.remote_ip != '127.0.0.1':
            self.finish('not allowed')
            return

        # self.add_header('access-control-allow-methods', 'OPTIONS, POST')
        # self.add_header('access-control-allow-origin', 'moz-extension://52ed146e-8386-4e74-9dae-5fe4e9ae20c8')
        global global_input

        blk = json.loads(self.request.body)
        chain = blk['chain']
        block_number = blk['block_number']
        block_hash = blk['block_hash'].replace('0x', '')
        # print(blk)
        transactions = [i['tx_hash'].replace('0x', '') for i, a in blk['txs']]
        if transactions:
            global_input.put(('%s-block-%s-%s' % (chain, str(setting.REVERSED_NO - block_number).zfill(16), block_hash)).encode('utf8'), json.dumps({'transactions': transactions}).encode('utf8'))
        # print(txs)
        tx_index = 0
        for data in blk['txs']:
            print(data)
            info = data[0]
            info['block_number'] = block_number
            info['block_hash'] = block_hash
            info['chain'] = chain
            space.info = info
            arg = data[1]
            global_input.put(('%s-blocktx-%s-%s' % (chain, block_hash, info['tx_hash'].replace('0x', ''))).encode('utf8'), json.dumps(info).encode('utf8'))
            global_input.put(('%s-tx-%s-%s' % (chain, info['tx_hash'].replace('0x', ''), block_hash)).encode('utf8'), json.dumps(arg).encode('utf8'))
            nonce = str(setting.REVERSED_NO - int(info['nonce'])).zfill(16)
            global_input.put(('%s-addr-%s-%s' % (chain, info['sender'].lower(), nonce)).encode('utf8'), json.dumps(info).encode('utf8'))
            # try:
            funcs.process(info, arg)
            # except:
            #     pass
            tx_index += 1

        if blk['txs']:
            space.merge()
        global_input.put(('%s-height' % (chain)).encode('utf8'), str(block_number).encode('utf8'))
        self.finish()
        # print(req['method'], req['params'])


class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
            (r'/(favicon\.ico)', tornado.web.StaticFileHandler, {'path': 'static/'}),
            (r'/static/(.*)', tornado.web.StaticFileHandler, {'path': 'static/'}),

            (r'/api/orderbook', OrderbookAPIHandler),
            (r'/api/get_latest_state', GetLatestStateAPIHandler),
            (r'/api/query_recent_state', QueryRecentStateAPIHandler),
            (r'/api/get_block', GetBlockAPIHandler),
            (r'/api/get_tx', GetTxAPIHandler),

            # (r'/address', AddressHandler),
            (r'/goto', GotoHandler),
            (r'/blocks', BlocksHandler),
            (r'/block', BlockHandler),
            (r'/tx', TxHandler),
            (r'/state', StateHandler),
            (r'/input', InputHandler),
            (r'/height', HeightHandler),
            (r'/entry', EntryHandler),
            (r'/', MainHandler),
        ]
        settings = {"debug":True}
        tornado.web.Application.__init__(self, handlers, **settings)


def jump():
    global global_input
    block_number = int(sys.argv[2])
    global_input.put(('%s-height' % ('base')).encode('utf8'), str(block_number).encode('utf8'))

# def clean():
#     global global_input
#     global global_state
#     # global pending_state

#     # it = global_input.iteritems()
#     st = global_state.iteritems()
#     k = b'base-'
#     st.seek(k)
#     c = 0
#     for key, value_json in st:
#         if not key.startswith(k):
#             break
#         if c % 1000 == 0:
#             print('delete', key)
#         c += 1
#         global_state.delete(key)

#     k = b'base_state_keys-'
#     st.seek(k)
#     c = 0
#     for key, value_json in st:
#         if not key.startswith(k):
#             break
#         if c % 1000 == 0:
#             print('remove state keys', key)
#         c += 1
#         global_state.delete(key)
#     global_input.put(('%s-height' % ('base')).encode('utf8'), str(1).encode('utf8'))

# def index():
#     global global_input
#     global global_state

#     it = global_input.iteritems()
#     st = global_state.iteritems()

#     min_block = int(global_input.get(('%s-height' % ('base')).encode()).decode())
#     # print('min_block', min_block)
#     if len(sys.argv) == 3 and sys.argv[1] == '-index':
#         min_block = int(sys.argv[2])

#     k = b'base-'
#     st.seek(k)
#     c = 0
#     for key, value_json in st:
#         if not key.startswith(k):
#             break
#         no = setting.REVERSED_NO - int(key.decode('utf8').split('-')[3])
#         if no >= min_block:
#             print('delete', min_block, no, key)
#             global_state.delete(key)
#         c += 1

#     k = b'base-block-'
#     it.seek(k)
#     max_block = 0

#     for key, value_json in it:
#         if not key.startswith(k):
#             break
#         if max_block == 0:
#             max_block = setting.REVERSED_NO - int(key.decode().split('-')[2])
#             break
#     print('min_block', min_block, 'max_block', max_block)

#     for i in range(min_block, max_block + 1):
#         k = ('base-block-%s-' % str(setting.REVERSED_NO - i).zfill(16)).encode()
#         # print(k)
#         # it.seek_to_first()
#         it.seek(k)
#         # value_json = global_input.get(key.encode())
#         for key, value_json in it:
#             if not key.startswith(k):
#                 break
#             value = json.loads(value_json)
#             if value['transactions']:
#                 print(i, value['transactions'])
#                 ks = key.decode('utf8').split('-')
#                 chain = ks[0] #blk['chain']
#                 height = setting.REVERSED_NO - int(ks[2]) #blk['block_number']
#                 block_hash = ks[3] #blk['block_hash'].replace('0x', '')
#                 # print(chain, height, block_hash)

#                 tx_index = 0
#                 for tx in value['transactions']:
#                     k2 = ('%s-tx-%s-' % (chain, tx)).encode()
#                     # print(k2)
#                     # it.seek_to_first()
#                     it.seek(k2)
#                     # value_json = global_input.get(key.encode())
#                     for key2, value_json2 in it:
#                         if not key2.startswith(k2):
#                             break
#                         # print(tx, value_json2)
#                         # value2 = json.loads(value_json2)
#                         # if value['transactions']:

#                         # blk = json.loads(value_json2)
#                         # transactions = [i['tx_hash'].replace('0x', '') for i, a in blk['txs']]
#                         # print(txs)
#                         info_value = global_input.get(('%s-blocktx-%s-%s' % (chain, block_hash, tx)).encode('utf8'))
#                         # print(data)
#                         info = json.loads(info_value) #data[0]
#                         info['block_number'] = height
#                         info['block_hash'] = block_hash
#                         info['chain'] = chain
#                         # print(info)
#                         arg = json.loads(value_json2) #data[1]
#                         # nonce = str(setting.REVERSED_NO - int(info['nonce'])).zfill(16)
#                         funcs.process(info, arg)
#                         tx_index += 1
#                         break

#                 space.merge()
#                 global_input.put(('%s-height' % (chain)).encode('utf8'), str(block_number).encode('utf8'))


#             break

def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--jump':
        jump()
        return

    # if len(sys.argv) > 1 and sys.argv[1] == '--clean':
    #     clean()
    #     return

    # if len(sys.argv) > 1 and sys.argv[1] == '--index':
    #     index()

    server = Application()
    server.listen(setting.INDEXER_PORT, '0.0.0.0')
    tornado.ioloop.IOLoop.instance().start()

if __name__ == '__main__':
    main()

