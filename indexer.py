# from __future__ import print_function

# import os
# import time
# import uuid
# import tracemalloc
# import hashlib
# import datetime
# import binascii
import json

# import tornado.options
import tornado.web
import tornado.ioloop
import tornado.httpclient
# import tornado.gen
# import tornado.escape

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

        buy_start, _ = get('trade', f'{base}_{quote}_buy_start', 1)
        # print(f'{base}_{quote}_buy_start')
        # print('buy_start', buy_start)
        buys = []
        buy_start0 = buy_start
        while True:
            buy, _ = get('trade', f'{base}_{quote}_buy', [], str(buy_start))
            # print('buy', buy)
            if not buy:
                break
            buys.append(buy)
            if buy[4] is None:
                break
            buy_start = buy[4]

        sell_start, _ = get('trade', f'{base}_{quote}_sell_start', 1)
        # print(f'{base}_{quote}_sell_start')
        # print('sell_start', sell_start)
        sells = []
        sell_start0 = sell_start
        while True:
            sell, _ = get('trade', f'{base}_{quote}_sell', [], str(sell_start))
            # print('sell', sell)
            if not sell:
                break
            sells.append(sell)
            if sell[4] is None:
                break
            sell_start = sell[4]

        self.finish({
            'buy_start': buy_start0,
            'buys': buys,
            'sell_start': sell_start0,
            'sells': sells
        })


class GetLatestStateAPIHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')

        global global_state
        # global pending_state

        prefix = self.get_argument('prefix')
        # chain = 'pow' pow-handle-handle2addr
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
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')

        global global_state
        # global pending_state

        prefix = self.get_argument('prefix')
        # chain = 'pow' pow-handle-handle2addr
        k = ('%s' % prefix).encode('utf8')
        it = global_state.iteritems()
        it.seek(k)
        result = {}
        for key, value_json in it:
            if not key.startswith(k):
                break
            ks = key.decode('utf8').split('-')
            result[setting.REVERSED_NO - int(ks[3])] = json.loads(value_json)
        self.finish(result)


class HistoryAPIHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')

        base = self.get_argument('base').upper()
        quote = self.get_argument('quote').upper()
        chain = 'base'
        target_pair = f"{base}_{quote}"
        print(f"HistoryAPI: base={base}, quote={quote}, target_pair={target_pair}")


        daily_ohlc = {}

        block_iter = global_input.iteritems()
        block_prefix = f'{chain}-block-'.encode('utf8')
        block_iter.seek(block_prefix)
        print(f"HistoryAPI: Seeking blocks with prefix: {block_prefix.decode()}")

        block_count = 0
        for key, value_json in block_iter:
            if not key.startswith(block_prefix):
                break
            block_count += 1

            try:
                _, _, reverse_no, block_hash = key.decode('utf8').split('-')
                block_data = json.loads(value_json)
                timestamp = block_data.get('timestamp', 0)
                tx_hashes = block_data.get('transactions', [])

                for tx_hash in tx_hashes:
                    tx_key = f'{chain}-tx-{tx_hash}-{block_hash}'.encode('utf8')
                    tx_value_json = global_input.get(tx_key)
                    if not tx_value_json:
                        continue
                    tx_data = json.loads(tx_value_json)
                    events = tx_data.get('events', [])

                    for event in events:
                        # event: [chain, 'TradeOrderTake', pair, buy_or_sell, addr, take_amount, price, cost]
                        if len(event) < 8 or event[1] != 'TradeOrderTake':
                            continue

                        pair = event[2]
                        if pair != target_pair:
                            continue

                        print(f"HistoryAPI: Found matching TradeOrderTake event: {event}")
                        price = event[6] / 10**6 # Assuming price has 6 decimals

                        if price == 0: # Skip if price is 0, which is the bug in zip22.py
                            print(f"HistoryAPI: Skipping event due to price being 0: {event}")
                            continue

                        # Group timestamps into 15-second intervals
                        interval = 60
                        time_bucket = (timestamp // interval) * interval

                        if time_bucket not in daily_ohlc:
                            daily_ohlc[time_bucket] = {
                                'open': price,
                                'high': price,
                                'low': price,
                                'close': price,
                                'first_trade_time': timestamp,
                                'last_trade_time': timestamp,
                            }
                        else:
                            bucket_data = daily_ohlc[time_bucket]
                            bucket_data['high'] = max(bucket_data['high'], price)
                            bucket_data['low'] = min(bucket_data['low'], price)

                            if timestamp < bucket_data['first_trade_time']:
                                bucket_data['open'] = price
                                bucket_data['first_trade_time'] = timestamp

                            if timestamp > bucket_data['last_trade_time']:
                                bucket_data['close'] = price
                                bucket_data['last_trade_time'] = timestamp
            except (ValueError, json.JSONDecodeError, TypeError) as e:
                print(f"Error processing block or transaction data: {e}")
                continue

        print(f"HistoryAPI: Processed {block_count} blocks.")
        chart_data = []
        for second_str, ohlc in sorted(daily_ohlc.items()):
            chart_data.append({
                'time': second_str,
                'open': ohlc['open'],
                'high': ohlc['high'],
                'low': ohlc['low'],
                'close': ohlc['close']
            })

        print(f"HistoryAPI: Returning {len(chart_data)} days of history.")
        self.finish({'history': chart_data})


class EventsAPIHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')

        global global_input
        chain = self.get_argument('chain', 'base')
        assert chain in setting.chains
        it1 = global_input.iteritems()
        events = []
        try:
            block_number = int(self.get_argument('blockno', None))
        except:
            tx_hash = self.get_argument('txhash', '')
            tx_hash = tx_hash.replace('0x', '')
            k = ('%s-tx-%s-' % (chain, tx_hash) ).encode('utf8')
            it1.seek(k)
            for key1, value_json1 in it1:
                print('key1', key1)
                if not key1.startswith(k):
                    break
                tx = json.loads(value_json1)
                events.append([tx_hash, tx['events']])

            self.finish({'events': events, 'tx_hash': tx_hash, 'chain':chain})
            return

        it = global_input.iteritems()
        reversed_height = str(setting.REVERSED_NO - block_number).zfill(16)
        k = ('%s-block-%s-' % (chain, reversed_height)).encode('utf8')
        it.seek(k)

        height_bytes = global_input.get(('%s-height' % (setting.chain)).encode('utf8'))
        height = int(height_bytes.decode('utf8')) if height_bytes else setting.INIT_HEIGHT

        block_hash = None
        for key, value_json in it:
            # print('block', block_number, key)
            if not key.startswith(k):
                break

            _, _, _, block_hash = key.decode('utf8').split('-')
            block = json.loads(value_json)
            tx_hashes = block.get('transactions', [])
            # chain = block['chain']
            for tx_hash in tx_hashes:
                k = ('%s-tx-%s-' % (chain, tx_hash) ).encode('utf8')
                it1.seek(k)
                for key1, value_json1 in it1:
                    print('key1', key1)
                    if not key1.startswith(k):
                        break
                    tx = json.loads(value_json1)
                    events.append([tx_hash, tx['events']])
                    break

            break

        if block_number > height:
            block_number = None
        self.finish({'events': events, 'blockno': block_number, 'block_hash': block_hash, 'chain':chain})


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
            self.block_number = value['info']['block_number']
            _, _, _, tx_hash = key.decode('utf8').split('-')
            self.txs.append([tx_hash, value['info']['tx_index']])

        self.render('template/block.html')

class TxHandler(tornado.web.RequestHandler):
    def get(self):
        tx_hash = self.get_argument('txhash').replace('0x', '')
        # print(tx_hash)
        global global_input
        self.chain = self.get_argument('chain', 'base')
        assert self.chain in setting.chains

        it = global_input.iteritems()
        it.seek(('%s-tx-%s-' % (self.chain, tx_hash)).encode('utf8'))
        self.tx_hash = ''
        for key, value_json in it:
            # print('tx', key, value_json)
            if not key.startswith(('%s-tx-%s-' % (self.chain, tx_hash)).encode('utf8')):
                break
            _, _, self.tx_hash, self.block_hash = key.decode('utf8').split('-')
            # print('self.tx_hash', self.tx_hash, 'self.block_hash', self.block_hash)

            value = json.loads(value_json)
            self.events = value['events']
            break

        it.seek(('%s-blocktx-%s-' % (self.chain, self.block_hash)).encode('utf8'))
        for key, value_json in it:
            # print('blocktx', key)
            if not key.startswith(('%s-blocktx-%s-' % (self.chain, self.block_hash)).encode('utf8')):
                break
            # self.write('%s %s<br>' % (key, value_json))
            value = json.loads(value_json)
            self.block_number = value['info']['block_number']
            self.tx_index = value['info']['tx_index']
            self.sender = value['info'].get('sender', '')
            self.args = value['args']
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
        self.page = int(self.get_argument('page', '0'))
        self.search = self.get_argument('search', '')
        
        try:
            self.block_number = int(self.get_argument('blockno'))
        except:
            try:
                self.block_number = int(global_input.get(('%s-height' % (self.chain)).encode('utf8')))
            except:
                self.block_number = 0

        self.state_keys = []
        self.state_values = {}
        
        if self.search:
            it = global_state.iteritems()
            search_prefix = ('%s-%s' % (self.chain, self.search)).encode('utf8')
            it.seek(search_prefix)
            
            skip_count = self.page * 100
            current_count = 0
            collected = 0
            
            for key, value_json in it:
                key_str = key.decode('utf8')
                
                # Check if key matches search prefix pattern
                if not key_str.startswith('%s-%s' % (self.chain, self.search)):
                    break
                
                try:
                    ks = key_str.split('-')
                    if len(ks) < 5:  # Need at least: chain-keyname-reversed_no-block_hash-sender
                        continue
                    
                    reversed_no = ks[-3]
                    no = setting.REVERSED_NO - int(reversed_no)
                    if no > self.block_number:
                        continue
                    
                    # Skip for pagination
                    if current_count < skip_count:
                        current_count += 1
                        continue
                    
                    if collected >= 100:
                        break
                    
                    # Extract key name (everything between chain and last 3 parts)
                    key_name = '-'.join(ks[1:-3])
                    
                    if key_name not in self.state_keys:
                        self.state_keys.append(key_name)
                        self.state_values[key_name] = (no, value_json.decode('utf8'))
                        collected += 1
                        current_count += 1
                except Exception as e:
                    continue
            
            self.render('template/state.html')
            return
        
        for i in range(100):
            # no = (str(setting.REVERSED_NO - self.block_number)).zfill(16)
            # k = ('%s_state_key-%s-%s' % (self.chain, i, no)).encode('utf8')
            k = ('%s_state_key-%s-' % (self.chain, i+self.page*100)).encode('utf8')
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
                # print('k2', k2)
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
            self.write('<br>%s<br>' % i)
            reversed_height = str(setting.REVERSED_NO - i).zfill(16)
            k = ('%s-block-%s-' % (chain, reversed_height)).encode('utf8')
            it.seek(k)
            # self.txs = []
            for key, value_json in it:
                print('block', i, key)
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
                    k = ('%s-tx-%s-' % (chain, tx_hash) ).encode('utf8')
                    it1.seek(k)
                    for key1, value_json1 in it1:
                        print('key1', key1)
                        if not key1.startswith(k):
                            break
                        _, _, _, block_hash = key1.decode('utf8').split('-')
                        self.write('%s<br>' % (value_json1))
                        break

                    k = ('%s-blocktx-%s-' % (chain, block_hash) ).encode('utf8')
                    it1.seek(k)
                    for key2, value_json2 in it1:
                        print('key2', key2)
                        if not key2.startswith(k):
                            break
                        self.write('%s<br>' % (value_json2))
                        break

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

class HeightAPIHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with, Content-Type")
        self.set_header('Access-Control-Allow-Methods', 'GET, OPTIONS')

    def options(self):
        # for CORS preflight
        self.set_status(204)
        self.finish()

    def get(self):
        global global_input

        chain = self.get_argument('chain')
        height = global_input.get(('%s-height' % chain).encode('utf8'))
        if height:
            height = int(height.decode('utf8'))
        self.finish({'chain': chain, 'height': height})


# class EntryHandler(tornado.web.RequestHandler):
#     def get(self):
#         global global_state

#         addr = self.get_argument('addr')
#         if addr.lower() == setting.account.address.lower():
#             self.finish({'entry': True, 'handle': setting.handle, 'credit': 10**18})
#         else:
#             handle = global_state.get(('zen-handle-addr2handle:%s' % (addr.lower())).encode('utf8'))
#             # if handle:
#             #     height = int(height.decode('utf8'))
#             self.finish({'entry': True, 'handle': handle.decode('utf8'), 'credit': 10**18})

class MainHandler(tornado.web.RequestHandler):
    def get(self):
        self.redirect('/blocks')

    # def post(self):
    #     if self.request.remote_ip != '127.0.0.1':
    #         self.finish('not allowed')
    #         return

    #     # self.add_header('access-control-allow-methods', 'OPTIONS, POST')
    #     # self.add_header('access-control-allow-origin', 'moz-extension://52ed146e-8386-4e74-9dae-5fe4e9ae20c8')
    #     global global_input

    #     blk = json.loads(self.request.body)
    #     chain = blk['chain']
    #     block_number = blk['block_number']
    #     block_hash = blk['block_hash'].replace('0x', '')
    #     timestamp = blk['timestamp']
    #     # print(blk)
    #     transactions = [i['tx_hash'].replace('0x', '') for i, a in blk['txs']]
    #     if transactions:
    #         global_input.put(('%s-block-%s-%s' % (chain, str(setting.REVERSED_NO - block_number).zfill(16), block_hash)).encode('utf8'), json.dumps({'transactions': transactions, 'timestamp': timestamp, 'chain': chain}).encode('utf8'))
    #     # print(txs)
    #     # space.block_number = block_number
    #     space.tx_index = 0
    #     space.block_number = block_number
    #     space.block_hash = block_hash
    #     space.chain = chain
    #     for data in blk['txs']:
    #         print(data)
    #         info = data[0]
    #         info['block_number'] = block_number
    #         info['block_hash'] = block_hash
    #         info['chain'] = chain
    #         info['sender'] = info['sender'].lower()
    #         info['timestamp'] = timestamp
    #         space.info = info

    #         args = data[1]
    #         func_name = args.get('f')
    #         space.func_name = func_name
    #         tx_hash = info['tx_hash'].replace('0x', '')
    #         k = ('%s-blocktx-%s-%s' % (chain, block_hash, tx_hash)).encode('utf8')
    #         global_input.put(k, json.dumps({'info': info, 'args': args}).encode('utf8'))
    #         nonce = str(setting.REVERSED_NO - int(info['nonce'])).zfill(16)
    #         global_input.put(('%s-addr-%s-%s' % (chain, info['sender'], nonce)).encode('utf8'), json.dumps(info).encode('utf8'))
    #         try:
    #             success = funcs.process(info, args)
    #         except Exception as e:
    #             print('Error:', func_name, e)
    #             success = False

    #         if not success:
    #             if space.tx_index in space.state_indexes:
    #                 space.state_indexes.remove(space.tx_index)
    #             if space.tx_index in space.states:
    #                 del space.states[space.tx_index]
    #             if space.tx_index in space.events:
    #                 del space.events[space.tx_index]

    #         events = space.events.get(space.tx_index, [])
    #         k = ('%s-tx-%s-%s' % (chain, tx_hash, block_hash)).encode('utf8')
    #         global_input.put(k, json.dumps({'block_number': block_number, 'chain': chain, 'success': success, 'events': events}).encode('utf8'))

    #         space.tx_index += 1

    #     space.merge()
    #     space.events = {}
    #     global_input.put(('%s-height' % (chain)).encode('utf8'), str(block_number).encode('utf8'))
    #     self.finish()


async def fetch_gazer():
    global global_input
    global height
    print('fetching gazer for height', height)

    http_client = tornado.httpclient.AsyncHTTPClient()
    try:
        response = await http_client.fetch(f'{setting.gazers[setting.chain]}/zentra/{height}')
    except Exception as e:
        print('Error fetching gazer:', e)
        tornado.ioloop.IOLoop.instance().call_later(1, fetch_gazer)
        return

    blk = json.loads(response.body)
    if not blk:
        print('No block found, waiting for 1 second')
        tornado.ioloop.IOLoop.instance().call_later(1, fetch_gazer)
        return

    chain = blk['chain']
    block_number = blk['block_number']
    block_hash = blk['block_hash'].replace('0x', '')
    timestamp = blk['timestamp']
    # print(blk)
    transactions = [i['tx_hash'].replace('0x', '') for i, a in blk['txs']]
    if transactions:
        global_input.put(('%s-block-%s-%s' % (chain, str(setting.REVERSED_NO - block_number).zfill(16), block_hash)).encode('utf8'), json.dumps({'transactions': transactions, 'timestamp': timestamp, 'chain': chain}).encode('utf8'))
    # print(txs)
    # space.block_number = block_number
    space.tx_index = 0
    space.block_number = block_number
    space.block_hash = block_hash
    space.chain = chain
    for data in blk['txs']:
        print(data)
        info = data[0]
        info['block_number'] = block_number
        info['block_hash'] = block_hash
        info['chain'] = chain
        info['sender'] = info['sender'].lower()
        info['timestamp'] = timestamp
        space.info = info

        args = data[1]
        func_name = args.get('f')
        space.func_name = func_name
        tx_hash = info['tx_hash'].replace('0x', '')
        k = ('%s-blocktx-%s-%s' % (chain, block_hash, tx_hash)).encode('utf8')
        global_input.put(k, json.dumps({'info': info, 'args': args}).encode('utf8'))
        nonce = str(setting.REVERSED_NO - int(info['nonce'])).zfill(16)
        global_input.put(('%s-addr-%s-%s' % (chain, info['sender'], nonce)).encode('utf8'), json.dumps(info).encode('utf8'))
        try:
            success = funcs.process(info, args)
        except Exception as e:
            print('Error:', func_name, e)
            success = False

        if not success:
            if space.tx_index in space.state_indexes:
                space.state_indexes.remove(space.tx_index)
            if space.tx_index in space.states:
                del space.states[space.tx_index]
            if space.tx_index in space.events:
                del space.events[space.tx_index]

        events = space.events.get(space.tx_index, [])
        k = ('%s-tx-%s-%s' % (chain, tx_hash, block_hash)).encode('utf8')
        global_input.put(k, json.dumps({'block_number': block_number, 'chain': chain, 'success': success, 'events': events}).encode('utf8'))

        space.tx_index += 1

    space.merge()
    space.events = {}
    global_input.put(('%s-height' % (chain)).encode('utf8'), str(block_number).encode('utf8'))
    height = block_number + 1
    tornado.ioloop.IOLoop.instance().add_callback(fetch_gazer)


class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
            (r'/(favicon\.ico)', tornado.web.StaticFileHandler, {'path': 'static/'}),
            (r'/static/(.*)', tornado.web.StaticFileHandler, {'path': 'static/'}),

            (r'/api/orderbook', OrderbookAPIHandler),
            (r'/api/history', HistoryAPIHandler),

            (r'/api/get_latest_state', GetLatestStateAPIHandler),
            (r'/api/query_recent_state', QueryRecentStateAPIHandler),
            (r'/api/events', EventsAPIHandler),
            (r'/api/height', HeightAPIHandler),

            (r'/goto', GotoHandler),
            (r'/blocks', BlocksHandler),
            (r'/block', BlockHandler),
            (r'/tx', TxHandler),
            (r'/state', StateHandler),
            (r'/input', InputHandler),
            # (r'/entry', EntryHandler),
            (r'/', MainHandler),
        ]
        settings = {"debug":True}
        tornado.web.Application.__init__(self, handlers, **settings)

height = 0
def main():
    global height
    # Read the height from the database instead of writing it
    height_bytes = global_input.get(('%s-height' % (setting.chain)).encode('utf8'))
    height = int(height_bytes.decode('utf8')) if height_bytes else setting.INIT_HEIGHT
    print("Latest height from database:", height)

    server = Application()
    print(f"Starting server on port {setting.INDEXER_PORT}")
    server.listen(setting.INDEXER_PORT, '0.0.0.0')
    tornado.ioloop.IOLoop.instance().add_callback(fetch_gazer)
    tornado.ioloop.IOLoop.instance().start()

if __name__ == '__main__':
    main()

