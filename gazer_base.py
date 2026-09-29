import sys
import os
import time
import json
import hashlib
import threading
# import uuid
import random

import web3
try:
    from web3.middleware import ExtraDataToPOAMiddleware as geth_poa_middleware
except ImportError:
    try:
        from web3.middleware import geth_poa_middleware
    except ImportError:
        from web3.middleware import geth_poa as geth_poa_middleware
import hexbytes
import eth_abi
import rocksdb

import tornado.web
import tornado.ioloop
import tornado.httpserver
import tornado.gen
import tornado.escape

import setting

CHAIN_NAME = 'base'
ZENTEST3_ADDR = "0x00000000000000000000000000000000007a656e"
REDEEMED_EVENT_TOPIC = '40dadaa36c6c2e3d7317e24757451ffb2d603d875f0ad5e92c5dd156573b1873'
REDEEM_METHOD_ID = 'cef6d209'

if not os.path.exists('states'):
    os.makedirs('states')
conn = rocksdb.DB('states/gazer-%s.db' % CHAIN_NAME, rocksdb.Options(create_if_missing=True))


PROVIDER_HOSTS = [ # for testnet3 now
    'https://base-sepolia.infura.io/v3/YOUR_KEY',
]


if '-d' in sys.argv:
    PROVIDER_HOSTS = ['http://127.0.0.1:8545']

w3s = []
for i in PROVIDER_HOSTS:
    w3 = web3.Web3(web3.Web3.HTTPProvider(i))
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    w3s.append(w3)


block_cache = {}
from_block = setting.INIT_HEIGHT # testnet3
if '-d' in sys.argv:
    from_block = 1

height_bytes = conn.get(b'height')
if height_bytes is not None:
    height = int(height_bytes.decode('utf-8'))
else:
    height = from_block

current_block = height
try:
    if '-f' == sys.argv[1]:
        current_block = int(sys.argv[2])
except:
    pass

fetch_height = current_block


def block_to_dict(block):
    if isinstance(block, dict):
        return {k: _convert_value(v) for k, v in block.items()}
    
    if hasattr(block, 'items') and callable(getattr(block, 'items')):
        try:
            return {k: _convert_value(v) for k, v in block.items()}
        except:
            pass
    
    result = {}
    if hasattr(block, '__getitem__'):
        try:
            for key in ['number', 'hash', 'parentHash', 'timestamp', 'transactions', 
                       'gasLimit', 'gasUsed', 'difficulty', 'totalDifficulty', 
                       'size', 'extraData', 'miner', 'nonce', 'baseFeePerGas']:
                try:
                    value = block[key]
                    result[key] = _convert_value(value)
                except (KeyError, TypeError):
                    continue
        except:
            pass
    
    if not result and hasattr(block, '__dict__'):
        for key, value in block.__dict__.items():
            if not key.startswith('_'):
                result[key] = _convert_value(value)
    
    return result


def _convert_value(value):
    if value is None:
        return None
    
    if isinstance(value, hexbytes.HexBytes):
        return value.hex()
    elif isinstance(value, bytes):
        return value.hex()
    
    if hasattr(value, 'hex') and not isinstance(value, (dict, list, tuple)):
        try:
            return value.hex()
        except:
            pass
    
    if isinstance(value, dict):
        return {k: _convert_value(v) for k, v in value.items()}
    
    if hasattr(value, 'items') and hasattr(value, 'keys'):
        try:
            return {k: _convert_value(v) for k, v in value.items()}
        except:
            pass
    
    if isinstance(value, (list, tuple)):
        return [_convert_value(item) for item in value]
    
    if hasattr(value, '__iter__') and not isinstance(value, (str, int, float, bool)):
        try:
            return [_convert_value(item) for item in value]
        except:
            pass
    
    return value


def fetch_block(height):
    global block_cache, w3s
    w3 = random.choice(w3s)
    print('fetch_block', height)
    sleep_time = 1
    while True:
        try:
            block = w3.eth.get_block(height, True)
            block_cache[height] = block
            break
        except Exception as e:
            print('Exception', e)
            time.sleep(sleep_time)
            sleep_time *= 2


def parse_redeem_input(data_hex):
    if not data_hex.startswith(REDEEM_METHOD_ID):
        return None
    raw = bytes.fromhex(data_hex[len(REDEEM_METHOD_ID):])
    types = ['bytes[]', 'bytes32[]', 'bytes[]']
    decoded = eth_abi.decode(types, raw)
    permission_contexts, modes, execution_call_datas = decoded
    return {
        'permission_contexts': [p.hex() for p in permission_contexts],
        'modes': [m.hex() for m in modes],
        'execution_call_datas': [d.hex() for d in execution_call_datas],
    }


def parse_redeemed_event(log):
    topics = log['topics']
    if topics[0].hex() != REDEEMED_EVENT_TOPIC:
        return None
    root_delegator = '0x' + topics[1].hex()[-40:]
    redeemer = '0x' + topics[2].hex()[-40:]
    delegation_type = '(address,address,bytes32,(address,bytes,bytes)[],uint256,bytes)'
    data = bytes(log['data'])
    delegation = eth_abi.decode([delegation_type], data)[0]
    delegate, delegator, authority, caveats, salt, signature = delegation
    return {
        'root_delegator': root_delegator,
        'redeemer': redeemer,
        'delegation': {
            'delegate': delegate,
            'delegator': delegator,
            'authority': authority.hex(),
            'caveats': [
                {
                    'enforcer': c[0],
                    'terms': c[1].hex(),
                    'args': c[2].hex(),
                }
                for c in caveats
            ],
            'salt': str(salt),
            'signature': signature.hex(),
        },
    }


def extract_zentest3_from_terms(terms_hex):
    terms = bytes.fromhex(terms_hex[2:] if terms_hex.startswith('0x') else terms_hex)
    if len(terms) < 20:
        return None
    target = '0x' + terms[:20].hex()
    if target.lower() != ZENTEST3_ADDR.lower():
        return None
    rest = terms[20:]
    brace = rest.find(b'{')
    if brace == -1:
        return None
    try:
        text = rest[brace:].decode('utf-8')
        obj = json.loads(text)
        if obj.get('p') == 'zentest3':
            return obj
    except Exception:
        pass
    return None


def process_block(block):
    global w3s
    w3 = random.choice(w3s)

    blk = {
        'txs': [],
        'block_number': block['number'],
        'block_hash': block['hash'].hex(),
        'chain': CHAIN_NAME,
        'timestamp': block['timestamp']
    }
    tx_index = 0
    for tx in block.transactions:
        try:
            to = tx['to'].lower()
        except:
            to = None
        if to == "0x00000000000000000000000000000000007a656e":
            print('tx hash', tx['hash'].hex())
            while True:
                try:
                    tx = w3.eth.get_transaction(tx['hash'])
                    break
                except:
                    print('retry tx hash', tx['hash'].hex())
                    time.sleep(0.5)
            # print('  tx', tx)
            print('  tx', tx['from'], tx['input'])

            info = {
                'sender': tx['from'].lower(),
                'nonce': tx['nonce'],
                'tx_index': tx_index,
                'tx_hash': tx['hash'].hex()
            }
            # print(tx['input'])
            try:
                input = json.loads(tx['input'])
                if type(input) is list:
                    for args in input:
                        try:
                            if args.get('p') == 'zentest3':
                                blk['txs'].append([info, args])
                        except:
                            pass
                else:
                    if input.get('p') == 'zentest3':
                        try:
                            blk['txs'].append([info, input])
                        except:
                            pass
            except:
                pass

        elif to == setting.METAMASK_GAS_PAYER and block['number'] >= setting.METAMASK_GAS_SPONSOR_HEIGHT:
            print('gas sponsor tx', tx['hash'].hex())
            while True:
                try:
                    tx_full = w3.eth.get_transaction(tx['hash'])
                    receipt = w3.eth.get_transaction_receipt(tx['hash'])
                    break
                except:
                    print('retry gas sponsor tx', tx['hash'].hex())
                    time.sleep(0.5)
            print('  tx', tx_full['from'])
            for log in receipt.logs:
                if log['address'].lower() != setting.METAMASK_GAS_PAYER:
                    continue
                ev = parse_redeemed_event(log)
                if not ev:
                    continue
                for caveat in ev['delegation']['caveats']:
                    z = extract_zentest3_from_terms(caveat['terms'])
                    if z:
                        info = {
                            'sender': ev['root_delegator'],
                            'nonce': tx_full['nonce'],
                            'tx_index': tx_index,
                            'tx_hash': tx['hash'].hex(),
                            'gas_sponsor': True,
                        }
                        blk['txs'].append([info, z])
                        print('  zentest3 from gas sponsor:', z)
                        break

        tx_index += 1

    return blk


def main():
    global current_block, fetch_height, w3s
    try:
        w3 = random.choice(w3s)
        latest_block = w3.eth.get_block_number()
    except:
        tornado.ioloop.IOLoop.instance().call_later(8, main)
        return

    print(current_block, fetch_height, latest_block, latest_block - current_block)
    if fetch_height > latest_block:
        tornado.ioloop.IOLoop.instance().call_later(3, main)
        return

    if fetch_height <= latest_block:
        print(threading.active_count(), block_cache.keys())
        if threading.active_count() < 5 and len(block_cache.keys()) < 7:
            to_height = min(fetch_height+3, latest_block+1)
            for i in range(fetch_height, to_height):
                thread = threading.Thread(target=fetch_block, args=[i])
                thread.start()
            fetch_height = to_height

    if current_block <= latest_block:
        # block = w3.eth.get_block(current_block, True)
        while True:
            block = block_cache.get(current_block)
            if block:
                print(current_block, len(block_cache.keys()))
                del block_cache[current_block]
                
                # 将 block 转换为 JSON 可序列化的字典
                block_dict = block_to_dict(block)
                block_json = json.dumps(block_dict)
                # print(f"Block {current_block} JSON:")
                # print(block_json)
                try:
                    conn.put(f'block_{current_block}'.encode(), block_json.encode('utf-8'))
                except Exception as e:
                    print(f"Failed to save block {current_block} to rocksdb:", e)
                
                blk = process_block(block)
                blk_json = json.dumps(blk)
                print(blk)
                try:
                    conn.put(f'zentra_{current_block}'.encode(), blk_json.encode('utf-8'))
                except Exception as e:
                    print(f"Failed to save block {current_block} to rocksdb:", e)

                try:
                    conn.put(b'height', str(current_block).encode())
                except Exception as e:
                    print("Failed to save block height to rocksdb:", e)
                current_block += 1
            else:
                break

    if current_block == latest_block:
        # tornado.gen.sleep(7)
        tornado.ioloop.IOLoop.instance().call_later(7, main)
    else:
        tornado.ioloop.IOLoop.instance().call_later(3, main)


class BlockHandler(tornado.web.RequestHandler):
    def get(self, block_height):
        # Get block_<height> from RocksDB and return as JSON, or 404
        key = f'block_{block_height}'.encode()
        value = conn.get(key)
        self.set_header("Content-Type", "application/json")
        if value is not None:
            self.finish(value)
        else:
            self.finish({})

class ZentraHandler(tornado.web.RequestHandler):
    def get(self, block_height):
        # Get zentra_<height> from RocksDB and return as JSON, or 404
        key = f'zentra_{block_height}'.encode()
        value = conn.get(key)
        self.set_header("Content-Type", "application/json")
        if value is not None:
            self.finish(value)
        else:
            self.finish({})


class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
            (r"/block/([0-9]+)", BlockHandler),
            (r"/zentra/([0-9]+)", ZentraHandler),
        ]
        settings = {"debug":True}
        tornado.web.Application.__init__(self, handlers, **settings)


if __name__ == '__main__':
    app = Application()
    app.listen(8091, '0.0.0.0')
    tornado.ioloop.IOLoop.instance().add_callback(main)
    tornado.ioloop.IOLoop.instance().start()
