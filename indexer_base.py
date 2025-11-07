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


CHAIN_NAME = 'base'


PROVIDER_HOST1 = 'https://base-sepolia.infura.io/v3/YOUR_KEY'
PROVIDER_HOST2 = 'https://base-sepolia.infura.io/v3/YOUR_KEY'
PROVIDER_HOST3 = 'https://base-sepolia.infura.io/v3/YOUR_KEY'


if '-d' in sys.argv:
    PROVIDER_HOST1 = 'http://127.0.0.1:8545'
    PROVIDER_HOST2 = 'http://127.0.0.1:8545'
    PROVIDER_HOST3 = 'http://127.0.0.1:8545'

w31 = web3.Web3(web3.Web3.HTTPProvider(PROVIDER_HOST1))
w32 = web3.Web3(web3.Web3.HTTPProvider(PROVIDER_HOST2))
w33 = web3.Web3(web3.Web3.HTTPProvider(PROVIDER_HOST3))

w31.middleware_onion.inject(web3.middleware.geth_poa_middleware, layer=0)
w32.middleware_onion.inject(web3.middleware.geth_poa_middleware, layer=0)
w33.middleware_onion.inject(web3.middleware.geth_poa_middleware, layer=0)


def fetch_block(height):
    global block_cache, w31, w32, w33
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

        to = tx['to'].lower() if tx['to'] else ''
        if tx['to'] == tx['from'] or to == "0x00000000000000000000000000000000007a656e":
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
from_block = 27340916 # first code deploy
if '-d' in sys.argv:
    from_block = 1

req = requests.get('http://127.0.0.1:%s/height?chain=base' % setting.INDEXER_PORT)
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
