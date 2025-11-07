import hashlib

# import eth_account

class Account:
    pass

account = Account()
account.address = '0xe1288759446298f250C3Bce5616706D25525Ba7F'.lower()
handle = 'powid'

account2 = Account()
account2.address = '0x06F40E30155779C46E002c8D73E0a0293eD5ee43'.lower()
handle2 = 'rewarder'

REVERSED_NO = 10**15

chains = {'cto', 'base'}
chain = 'base'
assets = {'ETH', 'USDT'}
appstates = set()

version = 1

# POWCHAIN_PORT = 8045
INDEXER_PORT = 8090
# POOL_PORT = 8070
# POOL_MINER = ''
