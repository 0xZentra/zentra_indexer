import sys
import hashlib
import math

import tornado
import tornado.escape

import setting
import database

import funcs

global_state = database.get_conn()
global_state_space = {}
states = {}
state_indexes = []

tx_index = 0
info = None

def _get_state_len(chain):
    it = global_state.iteritems()
    k = ('%s_state_len-' % (chain)).encode('utf8')
    it.seek(k)
    state_len = 0
    for key, value_json in it:
        if key.startswith(k):
            state_len = tornado.escape.json_decode(value_json.decode('utf8'))
            break
    return state_len

tree_cache = {0: {}}
state_len = _get_state_len(setting.chain)
print('> state_len', state_len)
it = global_state.iteritems()
it2 = global_state.iteritems()
for i in range(state_len):
    k = ('%s_state_key-%d-' % (setting.chain, i)).encode('utf8')
    it.seek(k)
    for key, value_json in it:
        if key.startswith(k):
            print('key', key, 'value_json', value_json)
            key_value = tornado.escape.json_decode(value_json)
            k2 = ('%s-%s-' % ('base', key_value)).encode('utf8')
            it2.seek(k2)
            for key2, value_json2 in it2:
                if key2.startswith(k2):
                    # tree_cache[0][i] = key_value
                    # print('key_value', key_value, 'value_json2', value_json2)
                    tree_cache[0][i] = hashlib.sha256(key_value.encode('utf8') + value_json2).hexdigest()
                break
        break
print('> tree_cache', tree_cache)

tree_height = 1
if state_len > 0:
    tree_capacity = 2 ** int(math.ceil(math.log2(state_len)))
    # print('tree_capacity', tree_capacity)
    tree_height = int(math.log2(tree_capacity))

# calculate the merkle root
for i in range(tree_height):
    tree_cache[i+1] = {}

    for p in tree_cache[i].keys():
        # print(p, int(p/2))
        ph = tree_cache[i][p]
        q = p-1 if p%2 else p+1
        if q in tree_cache[i]:
            qh = tree_cache[i][q]
            pair = sorted([ph, qh])
            # tree_cache.setdefault(i+1, {})
            tree_cache[i+1][int(p/2)] = hashlib.sha256((pair[0] + pair[1]).encode('utf8')).hexdigest()
            break
        tree_cache[i+1][int(p/2)] = hashlib.sha256((tree_cache[i][p]).encode('utf8')).hexdigest()
print('> tree_cache2', tree_cache)


def put(_owner, _asset, _var, _value, _key = None):
    global global_state
    global state_keys_updated
    global state_keys_removed

    assert type(_var) is str
    if _key is not None:
        assert type(_key) is str
        var = '%s:%s' % (_var, _key)
    else:
        var = _var

    asset_name = _asset
    addr = _owner.lower()
    k = '%s-%s' % (asset_name, var)
    state = states.get(tx_index, {})
    state[k] = [addr, _value]
    states[tx_index] = state

    if tx_index not in state_indexes:
        state_indexes.append(tx_index)


def get(_asset, _var, _default = None, _key = None):
    global info
    global global_state

    asset_name = _asset
    value = _default
    assert type(_var) is str
    if _key is not None:
        assert type(_key) is str
        var = '%s:%s' % (_var, _key)
    else:
        var = _var

    k = '%s-%s' % (asset_name, var)
    # print('get', k, 'tx_index', tx_index)
    state = states.get(tx_index, {})
    v = state.get(k)
    if v is not None:
        addr, value = v
        return value

    chain = info['chain']
    it = global_state.iteritems()
    k = '%s-%s-' % (chain, k)
    it.seek(k.encode('utf8'))
    for key, value_json in it:
        if key.startswith(k.encode('utf8')):
            value = tornado.escape.json_decode(value_json)
        break

    return value


def merge():
    global info
    global global_state
    global states
    global state_indexes
    # global merkle_roots
    global tree_cache

    # print('> merkle_roots', merkle_roots)
    # print('> tree_cache', tree_cache)
    # print('> info', info)
    chain = info['chain']
    block_number = info['block_number']
    block_hash = info['block_hash']
    reversed_block_no = str(setting.REVERSED_NO - block_number).zfill(16)
    state_keys_updated = set()
    state_keys_removed = set()

    # print('>> merge', block_number)
    # print('> state_keys_updated', state_keys_updated)
    # print('> state_indexes', state_indexes)
    for tx_index in reversed(state_indexes):
        state = states.get(tx_index)
        for key, addr_value in state.items():
        # addr_value = state.get(key)
            if addr_value is None:
                continue
            addr, value = addr_value
            global_state_space.setdefault(addr, 0)
            asset_name, var = key.split('-')
            it = global_state.iteritems()
            k = '%s-%s-%s-' % (chain, asset_name, var)
            k2 = '%s-%s' % (asset_name, var)
            it.seek(k.encode('utf8'))
            for key, value_json in it:
                if key.startswith(k.encode('utf8')):
                    global_state_space[addr] -= len(value_json)
                break

            value_json = tornado.escape.json_encode(value).encode('utf8')
            k3 = ('%s-%s-%s-%s-%s-%s' % (chain, asset_name, var, reversed_block_no, block_hash, addr)).encode('utf8')
            global_state.put(k3, value_json)
            if value is None:
                state_keys_removed.add(k2)
                if k2 in state_keys_updated:
                    state_keys_updated.remove(k2)
            else:
                global_state_space[addr] += len(value_json)
                # print('global_state_space', global_state_space)

                state_keys_updated.add(k2)
                if k2 in state_keys_removed:
                    state_keys_removed.remove(k2)

        break # as we only have 0 in state_indexes, will extend this later

    if not state_keys_updated and not state_keys_removed:
        return

    keys_update = [] # step 1
    keys_append = [] # step 2
    # keys_remove = [] # step 3
    keys = list(state_keys_updated)
    keys.sort() # important
    # print('> keys', keys)

    # print('> states', states[0])
    state_len = _get_state_len(chain)
    new_state_len = state_len

    keys_append_tuple = []
    keys_update_tuple = []
    for key in keys:
        it = global_state.iteritems()
        k = ('%s_state_idx-%s-' % (chain, key)).encode('utf8')
        it.seek(k)
        key_in_state_keys = False
        key_idx = None
        for key_value, value_json in it:
            if key_value.startswith(k):
                key_in_state_keys = True
                key_idx = tornado.escape.json_decode(value_json.decode('utf8'))
                break

        if not key_in_state_keys:
            # for never existing key, it is always an append
            # need to think
            keys_append.append(new_state_len)
            _addr, value = states[0][key]
            # print('value', _addr, value)
            keys_append_tuple.append((new_state_len, key, value))
            k = ('%s_state_idx-%s-%s' % (chain, key, reversed_block_no)).encode('utf8')
            global_state.put(k, tornado.escape.json_encode(new_state_len).encode('utf8'))
            k = ('%s_state_key-%s-%s' % (chain, new_state_len, reversed_block_no)).encode('utf8')
            global_state.put(k, tornado.escape.json_encode(key).encode('utf8'))
            new_state_len += 1
        else:
            keys_update.append(key_idx)
            _addr, value = states[0][key]
            print('value', _addr, value)
            keys_update_tuple.append((key_idx, key, value))
            k = ('%s_state_idx-%s-%s' % (chain, key, reversed_block_no)).encode('utf8')
            global_state.put(k, tornado.escape.json_encode(key_idx).encode('utf8'))
            k = ('%s_state_key-%s-%s' % (chain, key_idx, reversed_block_no)).encode('utf8')
            global_state.put(k, tornado.escape.json_encode(key).encode('utf8'))

    k = ('%s_state_len-%s' % (chain, reversed_block_no)).encode('utf8')
    global_state.put(k, tornado.escape.json_encode(new_state_len).encode('utf8'))

    keys_remove_tuple = []
    # print('> state_keys_removed', state_keys_removed)
    for key in state_keys_removed:
        # print('remove', key)
        it = global_state.iteritems()
        k = ('%s_state_idx-%s-' % (chain, key)).encode('utf8')
        it.seek(k)
        key_idx = None
        for key_value, value_json in it:
            if key_value.startswith(k):
                key_idx = tornado.escape.json_decode(value_json.decode('utf8'))
                break

        if key_idx is not None:
            # keys_remove.append(key_idx)
            k = ('%s_state_key-%s-%s' % (chain, key_idx, reversed_block_no)).encode('utf8')
            global_state.put(k, tornado.escape.json_encode(key).encode('utf8'))
            keys_remove_tuple.append((key_idx, key))

    tree_new = {0:{}}
    for p, key, val in keys_update_tuple:
        val_json = tornado.escape.json_encode(val)
        tree_new[0][p] = hashlib.sha256((key + val_json).encode('utf8')).hexdigest()

    # print('> keys_append_tuple', keys_append_tuple)
    for p, key, val in keys_append_tuple:
        val_json = tornado.escape.json_encode(val)
        tree_new[0][p] = hashlib.sha256((key + val_json).encode('utf8')).hexdigest()

    for p, key in keys_remove_tuple:
        tree_new[0][p] = hashlib.sha256(key.encode('utf8')).hexdigest()

    tree_height = 1
    if new_state_len > 0:
        tree_capacity = 2 ** int(math.ceil(math.log2(new_state_len)))
        # print('tree_capacity', tree_capacity)
        tree_height = int(math.log2(tree_capacity))

    # print('> tree_new', tree_new)
    # calculate the merkle root
    for i in range(tree_height):
        tree_new[i+1] = {}

        for p in tree_new[i]:
            # print(p, int(p/2))
            ph = tree_new[i][p]
            q = p-1 if p%2 else p+1
            if q in tree_new[i]:
                qh = tree_new[i][q]
                pair = sorted([ph, qh])
                tree_new[i+1][int(p/2)] = hashlib.sha256((pair[0] + pair[1]).encode('utf8')).hexdigest()
            elif q in tree_cache.get(i, {}):
                qh = tree_cache[i][q]
                pair = sorted([ph, qh])
                tree_new[i+1][int(p/2)] = hashlib.sha256((pair[0] + pair[1]).encode('utf8')).hexdigest()
            else:
                tree_new[i+1][int(p/2)] = hashlib.sha256((tree_new[i][p]).encode('utf8')).hexdigest()

    # print('> tree_new2', tree_new)
    # print('> tree_cache', tree_cache)
    for i in tree_new:
        tree_cache.setdefault(i, {})
    for i in tree_cache:
        tree_new.setdefault(i, {})
        tree_cache[i].update(tree_new[i])
    # print('> tree_cache2', tree_cache)

    state_root = tree_new[tree_height][0]
    # print('> state_root', state_root)
    k = ('%s_state_root-%s' % (chain, reversed_block_no)).encode('utf8')
    global_state.put(k, tornado.escape.json_encode(state_root).encode('utf8'))

    # print('> keys_update', keys_update) # step 1
    # print('> keys_append', keys_append) # step 2
    # print('> keys_remove', keys_remove) # step 3

    states = {}
    state_keys_updated = set()
    state_keys_removed = set()
    state_indexes = []


def has_appstate(_state):
    if _state in setting.appstates:
        return True
    return False


def call(fn, params):
    print('> call', fn)
    global info
    print('info', info)
    global states
    print('states', states)
    arg = {'p': 'zentest2', 'f': fn, 'a': params}
    funcs.process(info, arg)


def handle_resolve(_handle):
    # global block_number
    global sender

    addr = global_state.get(('handle-handle2addr:%s' % (_handle, )).encode('utf8'))
    if _handle == setting.handle:
        addr = setting.account.address.lower()
    return addr


def handle_lookup(_addr):
    # global block_number
    global sender

    handle = global_state.get(('handle-addr2handle:%s' % (_addr, )).encode('utf8'))
    if _addr.lower() == setting.account.address.lower():
        handle = setting.handle
    return handle

