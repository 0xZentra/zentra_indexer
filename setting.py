import hashlib

# import eth_account
INIT_HEIGHT = 29450134 # testnet3

REVERSED_NO = 10**15

chains = {'cto', 'base'}
chain = 'base'
gazers = {
    'base': 'http://127.0.0.1:8091',
}
assets = {'WETH', 'USDC', 'USDT'}
appstates = set()

version = 1

# POWCHAIN_PORT = 8045
INDEXER_PORT = 8090
# POOL_PORT = 8070
# POOL_MINER = ''
