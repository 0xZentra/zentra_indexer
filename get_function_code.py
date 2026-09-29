#!/usr/bin/env python3
"""Fetch Python source with bytecode disassembly of an on-chain zentest3 function.

Usage:
    python get_function_code.py <func_name>
    python get_function_code.py token_mint
    python get_function_code.py trade_limit_order
"""

import sys
import json
import dis
import ast
import urllib.request
import urllib.error
from itertools import groupby


API_BASE = 'https://testnet3.zentra.dev'


def api_get(prefix):
    url = '%s/api/get_latest_state?prefix=%s' % (API_BASE, prefix)
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0 (compatible; zentra-script)'},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('result')
    except Exception as e:
        print('API error:', e, file=sys.stderr)
        return None


def _walk_instrs(code, target_name=None):
    """Yield (line, offset, is_jump_target, instruction) recursively.
    When target_name is set, only the top-level code + the matching
    nested code object are walked."""
    last_line = None
    for instr in dis.Bytecode(code):
        ln = instr.starts_line if instr.starts_line is not None else last_line
        if ln is not None:
            yield (ln, instr.offset, instr.is_jump_target, instr)
        if instr.starts_line is not None:
            last_line = instr.starts_line

    if target_name is None:
        for const in code.co_consts:
            if hasattr(const, 'co_code'):
                yield from _walk_instrs(const, None)
    else:
        for const in code.co_consts:
            if hasattr(const, 'co_code') and const.co_name == target_name:
                yield from _walk_instrs(const, None)
                break


def _fmt_instr(instr, is_target):
    """Format one instruction line."""
    prefix = '     >>' if is_target else '       '
    s = '%s%4d  %-20s' % (prefix, instr.offset, instr.opname)
    if instr.arg is not None:
        r = instr.argrepr
        if instr.opname.startswith(('JUMP', 'FOR_ITER')):
            s += '  (to %d)' % instr.arg
        elif instr.opname in ('CALL_FUNCTION', 'CALL_FUNCTION_KW',
                              'CALL_FUNCTION_EX', 'MAKE_FUNCTION',
                              'BUILD_TUPLE', 'BUILD_LIST', 'BUILD_SET',
                              'BUILD_MAP', 'BUILD_STRING', 'UNPACK_SEQUENCE'):
            s += '  %s' % r
        elif instr.opname == 'LOAD_CONST':
            cv = instr.argval
            if hasattr(cv, 'co_code'):
                s += '  code %s' % cv.co_name
            else:
                s += '  %s' % r
        else:
            s += '  %s' % r
    return s


def _find_func_range(source, func_name):
    """Return (start_line, end_line) of func_name in source, or None."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name:
                return (node.lineno, node.end_lineno)
    return None


def print_source(source, func_name=None):
    lines = source.split('\n')
    width = len(str(len(lines)))

    # determine function line range
    frange = _find_func_range(source, func_name) if func_name else None

    # compile
    try:
        code = compile(source, '<onchain>', 'exec')
    except SyntaxError as e:
        for i, line in enumerate(lines, 1):
            if frange and (i < frange[0] or i > frange[1]):
                continue
            print('%*d  %s' % (width, i, line))
        print('\n# compile error: %s' % e, file=sys.stderr)
        return

    # collect & sort: (line, offset, is_jump_target, instr)
    items = sorted(_walk_instrs(code, func_name), key=lambda x: (x[0], x[1]))

    # group by line
    per_line = {}
    for ln, grp in groupby(items, key=lambda x: x[0]):
        per_line[ln] = [_fmt_instr(instr, tgt) for _, _, tgt, instr in grp]

    # print
    for i, line in enumerate(lines, 1):
        if frange and (i < frange[0] or i > frange[1]):
            continue
        print('%*d  %s' % (width, i, line))
        if i in per_line:
            for s in per_line[i]:
                print(s)


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)

    func_name = sys.argv[1]
    if func_name.startswith('function-code:'):
        func_name = func_name[len('function-code:'):]
    elif func_name.startswith('function-code%3A'):
        func_name = func_name[len('function-code%3A'):]

    # 1. get function-code record
    prefix = 'base-function-code:' + func_name
    code_data = api_get(prefix)
    if code_data is None:
        print('Function "%s" not found on chain.' % func_name, file=sys.stderr)
        print('Use the State page to browse available functions:',
              file=sys.stderr)
        print('  %s/state?search=function-code:' % API_BASE, file=sys.stderr)
        sys.exit(1)

    snippets = code_data.get('snippets', [])
    if not snippets:
        print('No snippets found for function "%s".' % func_name,
              file=sys.stderr)
        sys.exit(1)

    # 2. fetch each snippet and concatenate
    source_parts = []
    for h in snippets:
        prefix = 'base-function-snippet:' + h
        snip_data = api_get(prefix)
        if snip_data is None:
            print('Warning: snippet %s not found, skipping.' % h,
                  file=sys.stderr)
            continue
        source_parts.append(snip_data.get('snippet', ''))

    if not source_parts:
        print('Failed to retrieve any snippet source code.', file=sys.stderr)
        sys.exit(1)

    full_source = '\n'.join(source_parts)
    print_source(full_source, func_name)


if __name__ == '__main__':
    main()
