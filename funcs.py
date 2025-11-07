
import sys
import json
import hashlib
import string
import codeop

import setting
import database

import vm
import space
from space import get
from space import put
from space import handle_resolve
from space import handle_lookup

global_state = database.get_conn()
# global_input = database.get_conn_tx()


def committee_init(info, args):
    assert args['f'] == 'committee_init'
    sender = info['sender'].lower()
    handle = handle_lookup(sender)
    addr = handle or sender
    committee_members = get('committee', 'members', [])
    # print('committee_members', committee_members)
    assert not committee_members
    put(addr, 'committee', 'members', [addr])


def function_proposal(info, args):
    assert args['f'] == 'function_proposal'
    sender = info['sender']
    handle = handle_lookup(sender)
    addr = handle or sender
    fname = args['a'][0]
    assert set(fname) <= set(string.ascii_lowercase+'_')
    sourcecode = args['a'][1]

    require = args['a'][2]
    for i in require:
        assert type(i) is list
        assert set(i[0]) <= set(string.ascii_lowercase+'_')
        assert type(i[1]) is list
        for j in i[1]:
            assert set(j) <= set(string.ascii_uppercase+'_')

    asset_permission = args['a'][3]
    assert type(asset_permission) is list
    for i in asset_permission:
        assert i == '*' or set(i) <= set(string.ascii_lowercase+'_')

    invoke_permission = args['a'][4]
    assert type(invoke_permission) is list
    for i in invoke_permission:
        assert i == '*' or set(i) <= set(string.ascii_lowercase+'_')

    hexdigest = hashlib.sha256(sourcecode.encode('utf8')).hexdigest()
    k = 'function-proposal-%s:%s' % (fname, hexdigest)
    put(addr, 'function', 'proposal', {'sourcecode': sourcecode, 'asset_permission': asset_permission, 'require': require, 'votes': []}, '%s:%s' % (fname, hexdigest))


def function_vote(info, args):
    assert args['f'] == 'function_vote'
    sender = info['sender']
    handle = handle_lookup(sender)
    addr = handle or sender
    committee_members = set(get('committee', 'members', []))
    assert addr in committee_members

    fname = args['a'][0]
    sourcecode_hexdigest = args['a'][1]
    proposal = get('function', 'proposal', None, '%s:%s' % (fname, sourcecode_hexdigest))
    votes = set(proposal['votes'])
    votes.add(addr)
    proposal['votes'] = list(votes)

    if len(votes) >= len(committee_members)*2//3:
        put(addr, 'function', 'code', proposal, fname)
    else:
        put(addr, 'function', 'proposal', proposal, '%s:%s' % (fname, sourcecode_hexdigest))


def process(info, args):
    # global global_input

    block_number = info['block_number']
    space.block_number = block_number
    block_hash = info['block_hash']
    chain = info['chain']
    space.chain = chain
    assert args['p'] == 'zen'

    fname = args.get('f', '')
    code = get('function', 'code', {}, fname)
    sourcecode = code.get('sourcecode')
    # sourcecode = global_state.get(('%s-code-function:%s' % (chain, fname, )).encode('utf8'))

    if sourcecode is not None:
        # print(sourcecode)
        c = codeop.compile_command(sourcecode, symbol="exec")
        f = c.co_consts[0]
        # print(c.co_consts[0].co_code.hex())
        # print(c.co_consts[0].co_varnames)
        # print(c.co_consts[0].co_argcount)
        v = vm.VM()
        v.import_src(f)
        v.global_vars['string'] = string
        v.global_vars['hashlib'] = hashlib
        v.global_vars['json'] = json
        v.global_vars['get'] = get
        v.global_vars['put'] = put
        v.global_vars['handle_resolve'] = handle_resolve
        v.global_vars['handle_lookup'] = handle_lookup
        v.global_vars['print'] = print

        # TODO: put those in a function
        # v.global_vars['global_state'] = global_state
        # v.global_vars['setting'] = setting

        v.native_vars.add(get)
        v.native_vars.add(put)
        v.native_vars.add(handle_resolve)
        v.native_vars.add(handle_lookup)
        v.native_vars.add(print)
        v.native_vars.add(hashlib)
        v.run([info, args])

    elif args.get('f') == 'function_proposal':
        function_proposal(info, args)
    elif args.get('f') == 'function_vote':
        function_vote(info, args)
    elif args.get('f') == 'committee_init':
        committee_init(info, args)

    # print(state)
    # space.merge(block_hash)

