from miner import Miner
import random

m = Miner(None, None)

def makeblock(id_, parent):
    parent = str(parent)
    id_ = str(id_)
    return {
        "id": id_,
        "transactions": (),
        "mine": (),
        "timestamp": 0,
        "previous_block": parent
    }

def print_blocks():
    for block in m.blocks:
        print(block["id"])

def test_new_blocks():
    m.blocks = [makeblock(x+1, x)
                for x in range(6)]
    newblock4 = makeblock("new5", "4")
    newblock5 = makeblock("new6", "new5")
    newblock6 = makeblock("new7", "new6")
    falseblock10 = makeblock("false10", "new5")
    falseblock11 = makeblock("false11", "abc")
    m.resolve_block_conflict(newblock6)
    m.resolve_block_conflict(falseblock10)
    m.resolve_block_conflict(newblock5)
    m.resolve_block_conflict(falseblock11)
    m.resolve_block_conflict(newblock4)

    expected = ['1', '2', '3', '4', 'new5',
                       'new6', 'new7']

    print_blocks()
    assert expected == [x["id"] for x in m.blocks]

    
test_new_blocks()
        
