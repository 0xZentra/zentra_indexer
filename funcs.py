
import sys
import json
import hashlib
import string
import codeop

import setting
import database

from eth_utils import keccak

import vm
import space
from space import get
from space import put
from space import event
from space import funcs_reload
from space import handle_resolve
from space import handle_lookup

global_state = database.get_conn()
# global_input = database.get_conn_tx()


def committee_init(info, args):
    assert args['f'] == 'committee_init'
    sender = info['sender']
    addr = handle_lookup(sender)
    committee_members, _ = get('committee', 'members', [])
    # print('committee_members', committee_members)
    assert not committee_members
    put(addr, 'committee', 'members', [addr])
    event('CommitteeInit', [addr])


def function_snippet(info, args):
    assert args['f'] == 'function_snippet'
    sender = info['sender']
    addr = handle_lookup(sender)
    snippet = args['a'][0]
    snippet_digest = hashlib.sha256(snippet.encode('utf8')).hexdigest()
    put(addr, 'function', 'snippet', {
        'snippet': snippet,
        'functions': []
        }, snippet_digest)
    event('NewFunctionSnippet', [snippet_digest])


def function_proposal(info, args):
    assert args['f'] == 'function_proposal'
    sender = info['sender']
    addr = handle_lookup(sender)
    func_names = args['a'][0]
    snippet_digests = args['a'][1]
    for func_name in func_names:
        assert set(func_name) <= set(string.ascii_lowercase+string.digits+'_')
        assert not func_name.startswith('_')

    snippet_digests = args['a'][1]
    for snippet_digest in snippet_digests:
        assert set(snippet_digest) <= set(string.ascii_lowercase+string.digits)
        assert len(snippet_digest) == 64

    proposal_id, _ = get('function', 'proposal_count', 0)
    proposal_id += 1
    put(addr, 'function', 'proposal_count', proposal_id)

    put(addr, 'function', 'proposal', {
            'functions': func_names,
            'snippets': snippet_digests,
            'votes': []
        }, '%s' % (proposal_id))
    event('FunctionProposal', [proposal_id, func_names])


def function_vote(info, args):
    assert args['f'] == 'function_vote'
    sender = info['sender']
    addr = handle_lookup(sender)
    committee_members, _ = get('committee', 'members', [])
    committee_members = set(committee_members)
    assert addr in committee_members

    proposal_id = args['a'][0]
    proposal, _ = get('function', 'proposal', None, '%s' % proposal_id)
    assert proposal
    votes = set(proposal['votes'])
    votes.add(addr)
    proposal['votes'] = list(votes)

    # print(len(votes), len(committee_members), len(committee_members)*2//3)
    if len(votes) >= len(committee_members)*2//3:
        assert len(proposal['snippets']) > 0
        for snippet_hash in proposal['snippets']:
            assert set(snippet_hash) <= set(string.ascii_lowercase+string.digits)
            snippet, _ = get('function', 'snippet', None, snippet_hash)
            assert snippet, "Snippet not found: %s" % snippet_hash
            functions = snippet['functions']
            functions.extend(proposal['functions'])
            snippet['functions'] = list(set(functions))
            put('', 'function', 'snippet', snippet, snippet_hash)

        assert len(proposal['functions']) > 0
        for func_name in proposal['functions']:
            put(addr, 'function', 'code', {
                'snippets': proposal['snippets']
            }, func_name)

        funcs_reload(proposal['functions'])
        event('NewFunctions', [proposal_id, proposal['functions']])
    else:
        put(addr, 'function', 'proposal', proposal, '%s' % proposal_id)
        event('FunctionVote', [proposal_id, addr])


def process(info, args):
    # global global_input

    block_number = info['block_number']
    space.block_number = block_number
    # _block_hash = info['block_hash']
    chain = info['chain']
    space.chain = chain
    assert args['p'] == 'zentest3'

    # Multi-call chain format: {'p':'zentest3', 'c':[['f1', [a1]], ['f2', [a2], ...]]}
    if 'c' in args and block_number >= setting.MULTI_CALL_HEIGHT:
        for call_item in args['c']:
            if not isinstance(call_item, list) or len(call_item) < 1:
                continue
            func_name = call_item[0]
            func_args = call_item[1] if len(call_item) > 1 else []
            success = _process(info, func_name, func_args)
            if not success:
                return False
        return True

    return _process(info, args.get('f', ''), args.get('a', []))


def _process(info, func_name, func_args):
    args = {'p': 'zentest3', 'f': func_name, 'a': func_args}

    v = None
    if func_name in space.global_funcs:
        key = space.global_funcs[func_name]
        v = space.global_snippets[key]
    else:
        code, _ = get('function', 'code', {}, func_name)
        if code:
            snippets = code.get('snippets')
            print(snippets)
            key = '_'.join(snippets)
            if key in space.global_snippets:
                v = space.global_snippets[key]
            else:
                sourcecode = ''
                for snippet_hash in snippets:
                    snippet, _ = get('function', 'snippet', None, snippet_hash)
                    #print(snippet)
                    sourcecode += snippet.get('snippet', '') + '\n'
                # print('sourcecode', sourcecode)
                c = codeop.compile_command(sourcecode, symbol="exec")
                v = vm.VM()
                v.import_src(c)
                # print('co_code', c.co_code)

                v.global_vars['keccak'] = keccak
                v.global_vars['string'] = string
                v.global_vars['hashlib'] = hashlib
                v.global_vars['json'] = json
                v.global_vars['get'] = get
                v.global_vars['put'] = put
                v.global_vars['event'] = event
                v.global_vars['funcs_reload'] = funcs_reload
                v.global_vars['handle_resolve'] = handle_resolve
                v.global_vars['handle_lookup'] = handle_lookup
                v.global_vars['print'] = print
                v.global_vars['setting'] = setting

                v.native_vars.add(get)
                v.native_vars.add(put)
                v.native_vars.add(event)
                v.native_vars.add(funcs_reload)
                v.native_vars.add(handle_resolve)
                v.native_vars.add(handle_lookup)
                v.native_vars.add(print)
                v.native_vars.add(keccak)

                v.run([])
                space.global_funcs[func_name] = key
                space.global_snippets[key] = v

    success = True
    if v:
        success = v.run([info, args], function_name = func_name)
    elif func_name == 'function_vote':
        function_vote(info, args)
    elif func_name == 'function_proposal':
        function_proposal(info, args)
    elif func_name == 'function_snippet':
        function_snippet(info, args)
    elif func_name == 'committee_init':
        committee_init(info, args)

    return success
