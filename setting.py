import hashlib

# import eth_account
INIT_HEIGHT = 29450134 # testnet3
METAMASK_GAS_SPONSOR_HEIGHT = 42719361
MULTI_CALL_HEIGHT = 42757866
METAMASK_GAS_PAYER = "0xdb9b1e94b5b69df7e401ddbede43491141047db3"


REVERSED_NO = 10**15

chains = {'cto', 'base'}
chain = 'base'
gazers = {
    'base': 'http://127.0.0.1:8091',
    # 'base': 'http://10.128.0.2:8091',
}
assets = {'BTC', 'USDC'}
appstates = set()

version = 1

# POWCHAIN_PORT = 8045
INDEXER_PORT = 8090
# POOL_PORT = 8070
# POOL_MINER = ''
