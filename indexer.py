# from __future__ import print_function

# import os
# import time
# import uuid
# import tracemalloc
# import hashlib
# import datetime
# import binascii
import json
import time

# import tornado.options
import tornado.web
import tornado.ioloop
import tornado.websocket
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

stats_cache = {}


class SpotOrderbookAPIHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')

        base = self.get_argument('base').upper()
        quote = self.get_argument('quote').upper()
        pair = f'{base}_{quote}'
        space.info = {'chain': 'base'}

        buys = []
        sells = []

        buy_start, _ = get('trade', f'{pair}_buy_start', 1)
        sell_start, _ = get('trade', f'{pair}_sell_start', 1)

        buy_id = buy_start
        while buy_id:
            buy, _ = get('trade', f'{pair}_buy', None, str(buy_id))
            if buy:
                buys.append({
                    'id': buy_id,
                    'owner': buy[0],
                    'base': str(buy[1]),
                    'quote': str(buy[2]),
                    'price': str(buy[3]),
                    'next': buy[4]
                })
                buy_id = buy[4]
            else:
                break

        sell_id = sell_start
        while sell_id:
            sell, _ = get('trade', f'{pair}_sell', None, str(sell_id))
            if sell:
                sells.append({
                    'id': sell_id,
                    'owner': sell[0],
                    'base': str(sell[1]),
                    'quote': str(sell[2]),
                    'price': str(sell[3]),
                    'next': sell[4]
                })
                sell_id = sell[4]
            else:
                break

        self.finish({'buys': buys, 'sells': sells, 'pair': pair})


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
        interval = self.get_argument('interval', '1s')
        chain = 'base'
        target_pair = f"{base}_{quote}"

        interval_seconds = {
            '1s': 1, '1m': 60, '5m': 300, '15m': 900, '1h': 3600, '1d': 86400
        }
        if interval not in interval_seconds:
            interval = '1s'
        interval_sec = interval_seconds[interval]

        start_time_arg = self.get_argument('start_time', None)
        if start_time_arg:
            start_time = int(start_time_arg)
        else:
            start_time = int(time.time()) - interval_sec * 300

        buckets = {}
        last_trade_before_start = None

        block_iter = global_input.iteritems()
        block_prefix = f'{chain}-block-'.encode('utf8')
        block_iter.seek(block_prefix)

        for key, value_json in block_iter:
            if not key.startswith(block_prefix):
                break

            try:
                _, _, reverse_no, block_hash = key.decode('utf8').split('-')
                block_data = json.loads(value_json)
                timestamp = block_data.get('timestamp', 0)
                tx_hashes = block_data.get('transactions', [])

                if timestamp < start_time:
                    if last_trade_before_start is not None:
                        continue

                for tx_hash in tx_hashes:
                    tx_key = f'{chain}-tx-{tx_hash}-{block_hash}'.encode('utf8')
                    tx_value_json = global_input.get(tx_key)
                    if not tx_value_json:
                        continue
                    tx_data = json.loads(tx_value_json)
                    events = tx_data.get('events', [])

                    for event in events:
                        if len(event) > 2 and event[1] not in ('TradeLimitTake', 'TradeMarketTake'):
                            continue

                        pair = event[2]
                        if pair != target_pair:
                            continue

                        price = event[6]
                        if price == 0:
                            side = event[3]
                            order_id = event[7]
                            space.chain = 'base'
                            order, _ = get('trade', f'{pair}_{side}', None, str(order_id))
                            if order and len(order) >= 4:
                                price = order[3]
                        if price == 0:
                            continue

                        base_amount = event[5]
                        price_display = price / 10**6

                        if timestamp < start_time:
                            last_trade_before_start = {
                                'time': timestamp,
                                'price': price_display,
                                'amount': base_amount,
                                'side': event[3],
                            }
                        else:
                            bucket = (timestamp // interval_sec) * interval_sec
                            if bucket not in buckets:
                                buckets[bucket] = {
                                    'time': bucket,
                                    'open': price_display,
                                    'high': price_display,
                                    'low': price_display,
                                    'close': price_display,
                                    'volume': base_amount,
                                }
                            else:
                                b = buckets[bucket]
                                b['high'] = max(b['high'], price_display)
                                b['low'] = min(b['low'], price_display)
                                b['close'] = price_display
                                b['volume'] += base_amount
            except (ValueError, json.JSONDecodeError, TypeError) as e:
                continue

        candles = list(buckets.values())
        candles.sort(key=lambda x: x['time'])

        result = {'candles': candles, 'pair': target_pair}
        if last_trade_before_start:
            result['last_trade_before_start'] = last_trade_before_start
        self.finish(result)


class PredictOrderbookAPIHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')

        slug = self.get_argument('slug', 'btc_5min')

        def side_book(token, side):
            new, _ = get('predict', f'{slug}_{token}_{side}_new', None)
            orders = []
            if new is None:
                return orders
            for oid in range(1, int(new)):
                order, _ = get('predict', f'{slug}_{token}_{side}', None, str(oid))
                if not order or len(order) < 4:
                    continue
                if order[1] == 0:
                    continue
                price = int(order[3])
                if price <= 0:
                    continue
                orders.append({
                    'id': oid,
                    'owner': order[0],
                    'base': str(order[1]),
                    'quote': str(order[2]),
                    'price': str(price),
                })
            return orders

        result = {}
        for token in ['yes', 'no']:
            sells = sorted(side_book(token, 'sell'), key=lambda o: int(o['price']))
            buys = sorted(side_book(token, 'buy'), key=lambda o: -int(o['price']))
            result[token] = {
                'bestAsk': str(int(sells[0]['price']) / 10**18) if sells else None,
                'bestBid': str(int(buys[0]['price']) / 10**18) if buys else None,
                'asks': sells,
                'bids': buys,
            }

        self.finish({'slug': slug, 'result': result})


class Stats24hAPIHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')

        base = self.get_argument('base').upper()
        quote = self.get_argument('quote').upper()
        target_pair = f"{base}_{quote}"

        global stats_cache
        cached = stats_cache.get(target_pair)
        if cached and time.time() - cached['_ts'] < 60:
            resp = {k: v for k, v in cached.items() if k != '_ts'}
            self.finish(resp)
            return

        now = int(time.time())
        start_time = now - 86400

        high = 0.0
        low = float('inf')
        volume = 0.0
        open_price = None
        close_price = None
        trade_count = 0

        block_iter = global_input.iteritems()
        block_prefix = f'base-block-'.encode('utf8')
        block_iter.seek(block_prefix)

        for key, value_json in block_iter:
            if not key.startswith(block_prefix):
                break

            try:
                _, _, reverse_no, block_hash = key.decode('utf8').split('-')
                block_data = json.loads(value_json)
                timestamp = block_data.get('timestamp', 0)

                if timestamp < start_time:
                    continue
                if timestamp > now:
                    continue

                tx_hashes = block_data.get('transactions', [])

                for tx_hash in tx_hashes:
                    tx_key = f'base-tx-{tx_hash}-{block_hash}'.encode('utf8')
                    tx_value_json = global_input.get(tx_key)
                    if not tx_value_json:
                        continue
                    tx_data = json.loads(tx_value_json)
                    events = tx_data.get('events', [])

                    for event in events:
                        if len(event) > 2 and event[1] not in ('TradeLimitTake', 'TradeMarketTake'):
                            continue

                        pair = event[2]
                        if pair != target_pair:
                            continue

                        price = event[6]
                        if price == 0:
                            side = event[3]
                            order_id = event[7]
                            space.chain = 'base'
                            order, _ = get('trade', f'{pair}_{side}', None, str(order_id))
                            if order and len(order) >= 4:
                                price = order[3]
                        if price == 0:
                            continue

                        base_amount = event[5]
                        price_display = price / 10**6
                        base_amount_display = base_amount / 10**18

                        if open_price is None:
                            open_price = price_display
                        close_price = price_display

                        high = max(high, price_display)
                        low = min(low, price_display)
                        volume += base_amount_display
                        trade_count += 1

            except (ValueError, json.JSONDecodeError, TypeError) as e:
                continue

        if low == float('inf'):
            low = 0.0

        change = 0.0
        change_percent = 0.0
        if open_price and open_price > 0:
            change = close_price - open_price
            change_percent = (change / open_price) * 100

        result = {
            'pair': target_pair,
            'high': high,
            'low': low,
            'volume': volume,
            'open': open_price or 0,
            'close': close_price or 0,
            'change': change,
            'change_percent': change_percent,
            'trade_count': trade_count,
            'period_start': start_time,
            'period_end': now,
        }
        stats_cache[target_pair] = {**result, '_ts': now}
        self.finish(result)


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
    # print('fetching gazer for height', height)

    http_client = tornado.httpclient.AsyncHTTPClient()
    try:
        response = await http_client.fetch(f'{setting.gazers[setting.chain]}/zentra/{height}')
    except Exception as e:
        print('Error fetching gazer:', e)
        tornado.ioloop.IOLoop.instance().call_later(1, fetch_gazer)
        return

    blk = json.loads(response.body)
    if not blk:
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
        if 'c' in args:
            func_name = args['c'][0][0] if args['c'] else ''
        else:
            func_name = args.get('f', '')
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
        # Broadcast trade events via WS
        for evt in events:
            if len(evt) > 2 and evt[1] in ('TradeLimitTake', 'TradeMarketTake'):
                trade_pair = evt[2]
                parts = trade_pair.split('_')
                if len(parts) == 2:
                    base_asset, quote_asset = parts
                    price_raw = evt[6]
                    if price_raw == 0:
                        side = evt[3]
                        if len(evt) > 7 and evt[7] is not None:
                            order_id = evt[7]
                            order, _ = get('trade', f'{trade_pair}_{side}', None, str(order_id))
                            if order and len(order) >= 4:
                                price_raw = order[3]
                    if price_raw == 0:
                        continue
                    price_display = price_raw / (10**6)
                    trade_msg = json.dumps({
                        'type': 'trade',
                        'timestamp': timestamp,
                        'price': price_display,
                        'amount': evt[5] / (10**18),
                        'side': evt[3],
                        'pair': trade_pair
                    })
                    space.broadcast(trade_msg)

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

            (r'/api/orderbook', SpotOrderbookAPIHandler),
            (r'/api/spot_orderbook', SpotOrderbookAPIHandler),
            (r'/api/predict_orderbook', PredictOrderbookAPIHandler),
            (r'/api/history', HistoryAPIHandler),
            (r'/api/stats_24h', Stats24hAPIHandler),

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

