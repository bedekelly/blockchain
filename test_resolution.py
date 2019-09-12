from miner import Miner

m = Miner(None, None)

def makeblock(parent=0):
    return {
        "id": "new_block",
        "transactions": (),
        "mine": (),
        "timestamp": 0,
        "previous_block": parent
    }

m.blocks = [makeblock(str(x)) for x in range(5)]
m.resolve_block_conflict(makeblock(3))
print(m.blocks)
print(m.loser_blockchains)
    
    
