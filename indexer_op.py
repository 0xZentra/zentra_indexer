import sys
import time
import json
import hashlib
import threading
import uuid
import random

import web3
import hexbytes
import eth_abi
import requests

import setting


CHAIN_NAME = 'op'

# OP_PURCHASE_CONTRACT = '0xaEa9a28e079CcFD6Be1AB999395265d42cdE315F' # OP old
# OP_PURCHASE_CONTRACT = '0x7CdFB1fbf7d4E314E6c54577781DC7A7B00f2C9d' # OP USDT Purchase
# if '-d' in sys.argv:
#     OP_PURCHASE_CONTRACT = '0x9fE46736679d2D9a65F0992F2272dE9f3c7fa6e0' # hardhat

OP_PURCHASE_CONTRACTS = ['0xf3277Ecd65450BeFe656961B9Bfa25c3f1933EDB', '0x3F0f5bcC6a001C004A1C6AE2dd4151De0f513294'] # OP USDT Purchase

PROVIDER_HOST1 = 'https://optimism-mainnet.infura.io/v3/YOUR_KEY'
PROVIDER_HOST2 = 'https://optimism-mainnet.infura.io/v3/YOUR_KEY'
PROVIDER_HOST3 = 'https://optimism-mainnet.infura.io/v3/YOUR_KEY'
PROVIDER_HOST4 = 'https://distinguished-sleek-rain.optimism.quiknode.pro/YOUR_KEY'

if '-d' in sys.argv:
    OP_PURCHASE_CONTRACTS = ['0x9fE46736679d2D9a65F0992F2272dE9f3c7fa6e0', '0xCf7Ed3AccA5a467e9e704C703E8D87F634fB0Fc9'] # hardhat
    PROVIDER_HOST4 = 'http://127.0.0.1:8545'

#w3 = web3.Web3(web3.Web3.HTTPProvider('https://mainnet.infura.io/v3/YOUR_KEY'))
w31 = web3.Web3(web3.Web3.HTTPProvider(PROVIDER_HOST1))
w32 = web3.Web3(web3.Web3.HTTPProvider(PROVIDER_HOST2))
w33 = web3.Web3(web3.Web3.HTTPProvider(PROVIDER_HOST3))
w34 = web3.Web3(web3.Web3.HTTPProvider(PROVIDER_HOST4))

# w3 = web3.Web3(web3.Web3.WebsocketProvider(PROVIDER_WS))
w31.middleware_onion.inject(web3.middleware.geth_poa_middleware, layer=0)
w32.middleware_onion.inject(web3.middleware.geth_poa_middleware, layer=0)
w33.middleware_onion.inject(web3.middleware.geth_poa_middleware, layer=0)
w34.middleware_onion.inject(web3.middleware.geth_poa_middleware, layer=0)


HANDLE_LETTERS = 'abcdefghijklmnopqrstuvwxyz0123456789_'

def int2handle(handleint):
    v = handleint
    r = []
    for i in range(41, 0, -1):
        h = v // (38**i)
        # print(v, i, h, 37**i * h)
        if h:
            # print(h)
            r.append(HANDLE_LETTERS[h-1])
            v = v - (38**i * h)
            # print(v)
            if v < 38:
                # print(v)
                r.append(HANDLE_LETTERS[v-1])
    return ''.join(reversed(r))

def fetch_block(height):
    global block_cache, w34, w31, w32, w33
    # w3 = random.choice([w31, w32, w33])
    w3 = random.choice([w31, w32, w33])
    # if '-d' in sys.argv:
    #     w3 = w34
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


def process_block(block):
    global w34, w31, w32, w33
    w3 = random.choice([w31, w32, w33])

    blk = {'txs': [], 'block_number': block['number'], 'block_hash': block['hash'].hex(), 'chain': CHAIN_NAME}
    tx_index = 0
    for tx in block.transactions:
    # for tx_hash in block['transactions']:
        # tx = w3.eth.get_transaction(tx_hash)
        # print(tx)
        # tx = w3.eth.get_transaction(tx_hash)
        # print(tx['transactionIndex'], tx['to'])
        if tx['to'] in OP_PURCHASE_CONTRACTS:
            # print(transaction)
            while True:
                try:
                    tx_receipt = w3.eth.get_transaction_receipt(tx['hash'])
                    break
                except:
                    print('retry tx receipt', tx['hash'])
                    time.sleep(0.5)

            print(tx_receipt['logs'])
            for log in tx_receipt['logs']:
                if log['address'] in OP_PURCHASE_CONTRACTS:
                    print(log['topics'])
                    print(log['data'])
                    handleint, addr, price = eth_abi.decode(['uint256', 'address', 'uint256'], hexbytes.HexBytes(log['data']))
                    print(handleint, addr, price)
                    print(handleint, int2handle(handleint))
                    handle = int2handle(handleint)

                    info = {'sender': tx['from'].lower(), 'nonce': tx['nonce'], 'tx_hash': tx['hash'].hex(), 'invoke': 'event'}
                    arg = {'p': 'zen', 'f': 'handle_purchase', 'a': [handle, addr, price]}
                    blk['txs'].append([info, arg])

        if tx['to'] == tx['from']:
            print('tx hash', tx['hash'])
            while True:
                try:
                    tx = w3.eth.get_transaction(tx['hash'])
                    break
                except:
                    print('retry tx hash', tx['hash'])
                    time.sleep(0.5)
            # print('  tx', tx)
            print('  tx', tx['from'], tx['input'])

            try:
                info = {
                    'sender': tx['from'].lower(),
                    'nonce': tx['nonce'],
                    'block_number': block['number'], 
                    'block_hash': block['hash'].hex(),
                    'tx_index': tx_index,
                    'tx_hash': tx['hash'].hex()
                }
                # print(tx['input'])
                # arg = json.loads(w3.to_bytes(hexstr=tx['input']))
                input = json.loads(tx['input'])
                if type(input) is list:
                    for arg in input:
                        blk['txs'].append([info, arg])
                else:
                    blk['txs'].append([info, input])
            except:
                pass
        tx_index += 1

    return blk


block_cache = {}
# from_block = 120070853 # first test contract deploy
# from_block = 120071043 # first test contract purchase
# from_block = 128737759 # 2024 dec 1st deploy
from_block = 128740980 # first code deploy
if '-d' in sys.argv:
    from_block = 1

req = requests.get('http://127.0.0.1:%s/height?chain=op' % setting.INDEXER_PORT)
height = req.json()['height']
print(height)
if height:
    current_block = height
else:
    current_block = from_block
try:
    if '-f' == sys.argv[1]:
        current_block = int(sys.argv[2])
except:
    pass

try:
    if '-s' == sys.argv[1]:
        refetch_blocks = [int(i) for i in sys.argv[2:]]
        w3 = random.choice([w31, w32, w33])
        for height in refetch_blocks:
            print('fetch_block', height)
            block = w3.eth.get_block(height, True)
            blk = process_block(block)
            data = json.dumps(blk)
            while True:
                try:
                    requests.post('http://127.0.0.1:%s/' % setting.INDEXER_PORT, data=data.encode('utf8'))
                    break
                except:
                    time.sleep(0.5)

except:
    pass


fetch_height = current_block

w3 = random.choice([w31, w32, w33])
latest_block = w3.eth.get_block_number()
while True:
    time.sleep(0.5)
    print(current_block, fetch_height, latest_block, latest_block - current_block)
    if fetch_height >= latest_block:
        try:
            time.sleep(5)
            w3 = random.choice([w31, w32, w33])
            latest_block = w3.eth.get_block_number()
        except:
            continue

    if fetch_height <= latest_block:
        print(threading.active_count(), block_cache.keys())
        if threading.active_count() < 4 and len(block_cache.keys()) < 8:
            to_height = min(fetch_height+2, latest_block+1)
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
                # w3 = random.choice([w31, w32, w33])
                blk = process_block(block)

                # if blk['txs']:
                # print(blk['txs'])
                data = json.dumps(blk)
                while True:
                    try:
                        requests.post('http://127.0.0.1:%s/' % setting.INDEXER_PORT, data=data.encode('utf8'))
                        break
                    except:
                        time.sleep(0.5)

                current_block += 1
            else:
                break

    if current_block == latest_block:
        time.sleep(7)
