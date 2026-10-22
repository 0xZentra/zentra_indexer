ZEN_ADDR = "0x00000000000000000000000000000000007a656e"
import sys
import os
import time
import json
import threading
from dataclasses import dataclass
from collections import deque
from typing import Optional

import web3
try:
    from web3.middleware import ExtraDataToPOAMiddleware as geth_poa_middleware
except:
    try:
        from web3.middleware import geth_poa_middleware
    except:
        from web3.middleware import geth_poa as geth_poa_middleware
import hexbytes
import eth_abi
import rocksdb
import tornado.web
import tornado.ioloop
import setting

CHAIN_NAME='base'
REDEEMED_EVENT_TOPIC='40dadaa36c6c2e3d7317e24757451ffb2d603d875f0ad5e92c5dd156573b1873'
REDEEM_METHOD_ID='cef6d209'
LAG_THRESHOLD=2000
MIN_Q=150

if not os.path.exists('states'):
    os.makedirs('states')
conn=rocksdb.DB('states/gazer-%s.db'%CHAIN_NAME, rocksdb.Options(create_if_missing=True))

@dataclass
class RPCCfg:
    name:str
    url:str
    kind:str='free'
    archive: bool = False
    min_h:Optional[int]=None
    batch:int=12

FREE=[
    RPCCfg(name='sepolia.base.org', url='https://sepolia.base.org', kind='free', min_h=46500000, batch=12),
    RPCCfg(name='drpc',            url='https://base-sepolia.drpc.org', kind='free', min_h=46500000, batch=2),
    RPCCfg(name='tenderly',        url='https://base-sepolia.gateway.tenderly.co', kind='free', min_h=46500000, batch=5),
]

PAID=[
]


queue_lock=threading.Lock()
work_queue=deque()
in_queue=set()
block_cache={}
providers=[]

for config in FREE + PAID:
    try:
        web3_instance_init = web3.Web3(web3.Web3.HTTPProvider(config.url))
        web3_instance_init.middleware_onion.inject(geth_poa_middleware, layer=0)
        providers.append({'cfg': config, 'w': web3_instance_init, 'backoff': 1.0})
    except Exception as e:
        print('init', config.name, e)
print('providers', [provider_item['cfg'].name for provider_item in providers])

fetch_h = setting.INIT_HEIGHT
cur_h = fetch_h
latest_g = cur_h
lag = 0
if '-d' in sys.argv:
    fetch_h = 1
    cur_h = 1
try:
    value_height = conn.get(b'height')
    if value_height is not None:
        cur_h = int(value_height)
        fetch_h = cur_h
except Exception:
    pass
try:
    if len(sys.argv) > 2 and sys.argv[1] == '-f':
        cur_h = int(sys.argv[2])
        fetch_h = cur_h
except Exception:
    pass

assigned_from=fetch_h

def to_dict(b):
    if isinstance(b, dict): return {k:_cv(v) for k, v in b.items()}
    if hasattr(b, 'items') and callable(b.items):
        try: return {k:_cv(v) for k, v in b.items()}
        except: pass
    res={}
    try:
        for k in ['number', 'hash', 'parentHash', 'timestamp', 'transactions', 'gasLimit', 'gasUsed', 'difficulty', 'totalDifficulty', 'size', 'extraData', 'miner', 'nonce', 'baseFeePerGas']:
            try: res[k]=_cv(b[k])
            except: pass
    except: pass
    try:
        if isinstance(getattr(b, '__dict__', None), dict):
            for k, v in b.__dict__.items():
                if k.startswith('_'): continue
                res[k]=_cv(v)
    except: pass
    return res

def _cv(v):
    if v is None: return None
    if type(v).__name__ == 'HexBytes' or isinstance(v, hexbytes.HexBytes): return v.hex()
    if isinstance(v, bytes): return v.hex()
    if hasattr(v, 'hex') and not isinstance(v, (dict, list, tuple, str)):
        try:
            h=v.hex()
            if isinstance(h, str): return h
        except: pass
    if isinstance(v, dict): return {k:_cv(x) for k, x in v.items()}
    if hasattr(v, 'items') and callable(v.items):
        try: return {k:_cv(x) for k, x in v.items()}
        except: pass
    if isinstance(v, (list, tuple)): return [_cv(x) for x in v]
    if isinstance(v, (int, float, bool, str)): return v
    try:
        if hasattr(v, '__dict__'):
            return {k:_cv(x) for k, x in v.__dict__.items() if not k.startswith('_')}
    except: pass
    return str(v)

def is_eligible(p, h):
    config_p = p['cfg']
    if config.min_h is not None and h<config.min_h: return False
    if h<46500000 and not config.archive: return False
    return True

def push_front(hs):
    for h in reversed(hs):
        if h in in_queue: continue
        in_queue.add(h)
        work_queue.appendleft(h)

def push_back(hs):
    for h in hs:
        if h in in_queue: continue
        if h in block_cache: continue
        in_queue.add(h)
        work_queue.append(h)

def enqueue_on_demand(h):
    if h in block_cache: return
    with queue_lock:
        if h in in_queue: return
        in_queue.add(h)
        work_queue.appendleft(h)
        print('ondemand enqueue', h)

def refill():
    global assigned_from, latest_g
    with queue_lock:
        if len(work_queue) >= MIN_Q:
            return
        if assigned_from > latest_g + 5:
            return
        count_refill = 0
        while len(work_queue) < MIN_Q and assigned_from <= latest_g and count_refill < MIN_Q * 2:
            if assigned_from in block_cache:
                assigned_from += 1
                count_refill += 1
                continue
            if assigned_from in in_queue:
                assigned_from += 1
                count_refill += 1
                continue
            in_queue.add(assigned_from)
            work_queue.append(assigned_from)
            assigned_from += 1
            count_refill += 1

def fetch_one_rpc(provider_info):
    global lag, latest_g
    config = provider_info['cfg']
    web3_instance = provider_info['w']
    while True:
        try:
            if config.kind == 'paid' and lag < LAG_THRESHOLD:
                time.sleep(1)
                continue
            refill()
            hs=[]
            with queue_lock:
                while len(hs) <= config.batch and work_queue:
                    h = work_queue.popleft()
                    try:
                        in_queue.discard(h)
                    except Exception:
                        pass
                    if h in block_cache:
                        continue
                    hs.append(h)
            if not hs:
                time.sleep(1)
                continue
            # filter eligible for this rpc
            take=[]
            back=[]
            for h in hs:
                if is_eligible(p, h):
                    take.append(h)
                else:
                    back.append(h)
            if back:
                with queue_lock:
                    for h in reversed(back):
                        if h in in_queue: continue
                        in_queue.add(h)
                        work_queue.appendleft(h)
            if not take:
                time.sleep(1)
                continue
            miss=list(take)
            got={}
            print('rpc', config.name, 'batch', len(miss), miss[0], '-', miss[-1])
            try:
                b = web3_instance.batch_requests()
                for h in miss: b.add(web3_instance.eth.get_block(h, True))
                reps=b.execute()
                for i, h in enumerate(miss):
                    if i < len(reps):
                        blk=reps[i]
                        if blk is not None and not isinstance(blk, Exception):
                            got[h]=blk
            except Exception as e:
                print('be', config.name, e)
            # fallback missing
            for h in miss:
                if h in got: continue
                try:
                    blk = web3_instance.eth.get_block(h, True)
                    if blk: got[h]=blk
                except Exception as ee:
                    print('ie', config.name, h, ee)
            # store
            for h, blk in got.items():
                block_cache[h]=blk
            # failed
            failed=[h for h in miss if h not in got]
            if failed:
                with queue_lock:
                    for h in reversed(failed):
                        if h in in_queue: continue
                        if h in block_cache: continue
                        in_queue.add(h)
                        work_queue.appendleft(h)
                p['backoff']=min(p['backoff']*2.0, 30.0)
                time.sleep(p['backoff'])
            else:
                p['backoff']=1.0
                time.sleep(1.0)
        except Exception as e:
            print('rpe', config.name, e)
            time.sleep(2)

for p in providers:
    t=threading.Thread(target=fetch_one_rpc, args=[p], daemon=True)
    t.start()

def get_provider(h=None):
    if h is not None and h<46500000:
        for p in providers:
            if p['cfg'].archive and is_eligible(p, h): return p
    for p in providers:
        if p['cfg'].kind == 'free' and is_eligible(p, h if h is not None else 10**19): return p
    for p in providers:
        if is_eligible(p, h if h is not None else 10**19): return p
    return providers[0] if providers else None

def process_block(block):
    if isinstance(block, (list, tuple)):
        try:
            block = block[0]
        except Exception:
            pass
    try:
        if isinstance(block, dict):
            block_height_num = block['number']
        elif hasattr(block, '__getitem__'):
            block_height_num = block['number']
        else:
            block_height_num = getattr(block, 'number')
    except Exception:
        block_height_num = 0
    provider_info_pb = get_provider(block_height_num)
    if provider_info_pb and providers:
        web3_instance_pb = provider_info_pb['w']
    elif providers:
        web3_instance_pb = providers[0]['w']
    else:
        web3_instance_pb = None
    h = block_height_num
    try: bnum=h
    except: bnum=0
    try:
        if isinstance(block, dict):
            bhv=block.get('hash')
        else:
            bhv=getattr(block, 'hash', None)
        if bhv is None:
            bh=''
        elif hasattr(bhv, 'hex') and not isinstance(bhv, str):
            h=bhv.hex()
            bh='0x'+h if not h.startswith('0x') else h
        elif isinstance(bhv, bytes):
            bh='0x'+bhv.hex()
        elif isinstance(bhv, str):
            bh=bhv if bhv.startswith('0x') else '0x'+bhv
        else:
            bh=str(bhv)
    except Exception:
        bh=''
    try:
        if isinstance(block, dict):
            bts=block.get('timestamp', 0)
        else:
            bts=getattr(block, 'timestamp', 0)
    except Exception:
        bts=0
    blk={'txs':[], 'block_number':int(bnum), 'block_hash':bh, 'chain':CHAIN_NAME, 'timestamp':bts}
    try: txs=block.transactions if hasattr(block, 'transactions') else (block.get('transactions') if isinstance(block, dict) else [])
    except: txs=[]
    ti=0
    for tx in txs:
        try:
            to=tx['to']
            if hasattr(to, 'lower'): to=to.lower()
            elif isinstance(to, str): to=to.lower()
            else: to=None
        except: to=None
        if to == ZEN_ADDR:
            try:
                tx_hash_print = tx['hash'].hex() if hasattr(tx.get('hash'), 'hex') else tx.get('hash')
                print('tx', tx_hash_print)
            except Exception:
                pass
            tr = 0
            txcur = tx
            while tr < 10 and web3_instance_pb:
                try:
                    txcur = web3_instance_pb.eth.get_transaction(tx['hash'])
                    break
                except Exception:
                    tr += 1
                    time.sleep(0.3)
            try:
                tx=txcur
                thx=tx['hash'].hex() if hasattr(tx['hash'], 'hex') else str(tx['hash'])
                info={'sender':str(tx['from']).lower(), 'nonce':int(tx['nonce']), 'tx_index':ti, 'tx_hash':thx}
                inp=tx['input']
                if isinstance(inp, bytes): inp=inp.hex()
                inpj=json.loads(inp)
                if isinstance(inpj, list):
                    for a in inpj:
                        if isinstance(a, dict) and a.get('p') == 'zentest3': blk['txs'].append([info, a])
                elif isinstance(inpj, dict) and inpj.get('p') == 'zentest3': blk['txs'].append([info, inpj])
            except Exception as e: print('txe', e)
        elif to == setting.METAMASK_GAS_PAYER.lower() and block_height_num >= setting.METAMASK_GAS_SPONSOR_HEIGHT:
            try:
                print('gs', tx['hash'].hex() if hasattr(tx['hash'], 'hex') else tx['hash'])
            except Exception:
                pass
            tr = 0
            txf = None
            rcpt = None
            while tr < 10 and web3_instance_pb:
                try:
                    txf = web3_instance_pb.eth.get_transaction(tx['hash'])
                    rcpt = web3_instance_pb.eth.get_transaction_receipt(tx['hash'])
                    break
                except Exception:
                    tr += 1
                    time.sleep(0.3)
            else:
                ti += 1
                continue
            try:
                rc = rcpt
                for lg in rc.logs:
                    if lg['address'].lower() != setting.METAMASK_GAS_PAYER.lower(): continue
                    topics = lg['topics']
                    if topics[0].hex() != REDEEMED_EVENT_TOPIC:
                        continue
                    root_delegator_addr = '0x' + topics[1].hex()[-40:]
                    redeemer_addr = '0x' + topics[2].hex()[-40:]
                    delegation_type = '(address,address,bytes32,(address,bytes,bytes)[],uint256,bytes)'
                    de = eth_abi.decode([delegation_type], bytes(lg['data']))[0]
                    dl, dr, au, cv, sl, sig=de
                    ev={'root_delegator':root_delegator_addr, 'redeemer':redeemer_addr, 'delegation':{'delegate':dl, 'delegator':dr, 'authority':au.hex(), 'caveats':[{'enforcer':c[0], 'terms':c[1].hex(), 'args':c[2].hex()} for c in cv], 'salt':str(sl), 'signature':sig.hex()}}
                    for cv in ev['delegation']['caveats']:
                        t=bytes.fromhex(cv['terms'][2:] if cv['terms'].startswith('0x') else cv['terms'])
                        if len(t) < 20:
                            continue
                        if t[:20].hex().lower() != ZEN_ADDR[2:].lower():
                            continue
                        rest = t[20:]
                        brace_pos = rest.find(b'{')
                        if brace_pos == -1:
                            continue
                        try:
                            obj=json.loads(rest[brace_pos:].decode())
                            if obj.get('p') == 'zentest3':
                                blk['txs'].append([{'sender':ev['root_delegator'], 'nonce':txf['nonce'], 'tx_index':ti, 'tx_hash':tx['hash'].hex(), 'gas_sponsor':True}, obj])
                                break
                        except: pass
            except Exception as e: print('gse', e)
        ti+=1
    return blk

def main():
    global cur_h, latest_g, lag, assigned_from
    try:
        provider_info_main = get_provider(cur_h)
        if provider_info_main and providers:
            web3_instance_main = provider_info_main['w']
        elif providers:
            web3_instance_main = providers[0]['w']
        else:
            web3_instance_main = None
        if not web3_instance_main:
            tornado.ioloop.IOLoop.instance().call_later(5, main)
            return
        latest_block_number = web3_instance_main.eth.get_block_number()
        latest_g = latest_block_number
        if latest_g >= cur_h:
            lag = latest_g - cur_h
        else:
            lag = 0
        refill()
    except Exception as e:
        print('me', e)
        tornado.ioloop.IOLoop.instance().call_later(5, main)
        return
    print(cur_h, latest_g, lag, 'q', len(work_queue))
    if cur_h <= latest_g:
        while True:
            blk=block_cache.get(cur_h)
            if blk:
                try: del block_cache[cur_h]
                except: pass
                try: conn.put(f'block_{cur_h}'.encode(), json.dumps(to_dict(blk)).encode())
                except Exception as e: print('db', e)
                try:
                    if isinstance(blk, (list, tuple)):
                        blk2 = blk[0]
                    else:
                        blk2 = blk
                    block_zentra = process_block(blk2)
                    conn.put(f'zentra_{cur_h}'.encode(), json.dumps(block_zentra).encode())
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    print('db2', e)
                try: conn.put(b'height', str(cur_h).encode())
                except: pass
                cur_h+=1
            else: break
    if cur_h >= latest_g: tornado.ioloop.IOLoop.instance().call_later(7, main)
    else: tornado.ioloop.IOLoop.instance().call_later(1, main)

class BlockHandler(tornado.web.RequestHandler):
    def get(self, h):
        print('indexer req block', h)
        hh = int(h)
        v = conn.get(f'block_{hh}'.encode())
        if v is None:
            if hh not in block_cache:
                enqueue_on_demand(hh)
            v = conn.get(f'block_{hh}'.encode())
        self.set_header("Content-Type", "application/json")
        self.finish(v if v is not None else {})


class ZentraHandler(tornado.web.RequestHandler):
    def get(self, h):
        print('indexer req zentra', h)
        hh = int(h)
        v = conn.get(f'zentra_{hh}'.encode())
        if v is None:
            if hh not in block_cache:
                enqueue_on_demand(hh)
            # try process if available
            blk=block_cache.get(hh)
            if blk and v is None:
                try:
                    if isinstance(blk, (list, tuple)): blk2=blk[0]
                    else: blk2=blk
                    b2=process_block(blk2)
                    try: del block_cache[hh]
                    except: pass
                    try: conn.put(f'block_{hh}'.encode(), json.dumps(to_dict(blk2)).encode())
                    except: pass
                    try: conn.put(f'zentra_{hh}'.encode(), json.dumps(b2).encode())
                    except Exception as ee:
                        import traceback
                        traceback.print_exc()
                        print('oz', ee)
                    try: conn.put(b'height', str(max(cur_h, hh+1)).encode())
                    except: pass
                    v=conn.get(f'zentra_{hh}'.encode())
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    print('onreq proc err', e)
        self.set_header("Content-Type", "application/json")
        self.finish(v if v is not None else {})

class App(tornado.web.Application):
    def __init__(self):
        tornado.web.Application.__init__(self, [
            (r"/block/([0-9]+)", BlockHandler),
            (r"/zentra/([0-9]+)", ZentraHandler)
        ], debug=True)

if __name__ == '__main__':
    app=App()
    app.listen(8091, '0.0.0.0')
    tornado.ioloop.IOLoop.instance().add_callback(main)
    tornado.ioloop.IOLoop.instance().start()
