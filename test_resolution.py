from miner import Miner

m = Miner(None, None)


def make_block(id_, parent):
    parent = str(parent)
    id_ = str(id_)
    return {
        "id": id_,
        "transactions": (),
        "mine": (),
        "timestamp": 0,
        "previous_block": parent,
    }


def print_blocks():
    for block in m.blocks:
        print(block["id"])


def test_reverse_order():
    m.blocks = [make_block(x + 1, x) for x in range(6)]
    m.loser_blockchains = []
    block4 = make_block("new5", "4")
    block5 = make_block("new6", "new5")
    block6 = make_block("new7", "new6")
    wrong_block6 = make_block("false10", "new5")
    wrong_block_abc = make_block("false_abc", "abc")
    m.resolve_block_conflict(block6)
    m.resolve_block_conflict(wrong_block6)
    m.resolve_block_conflict(block5)
    m.resolve_block_conflict(wrong_block_abc)
    m.resolve_block_conflict(block4)

    expected = ["1", "2", "3", "4", "new5", "new6", "new7"]
    assert [x["id"] for x in m.blocks] == expected


def test_fill_reverse_gap():
    m.blocks = [make_block(x + 1, x) for x in range(6)]
    m.loser_blockchains = []
    block5 = make_block("new-5", "4")
    block6 = make_block("new-6", "new-5")
    block7 = make_block("new-7", "new-6")
    wrong_block6 = make_block("false10", "new-5")
    wrong_block_abc = make_block("false_abc", "abc")
    m.resolve_block_conflict(block7)
    m.resolve_block_conflict(wrong_block6)
    m.resolve_block_conflict(block5)
    m.resolve_block_conflict(wrong_block_abc)
    m.resolve_block_conflict(block6)

    expected = ["1", "2", "3", "4", "new-5", "new-6", "new-7"]
    assert [x["id"] for x in m.blocks] == expected


def test_fill_gap():
    m.blocks = [make_block(x + 1, x) for x in range(5)]
    m.loser_blockchains = []
    block4 = make_block("new4", "3")
    block5 = make_block("new5", "new4")
    block6 = make_block("new6", "new5")

    m.resolve_block_conflict(block4)  # new4
    m.resolve_block_conflict(block6)  # new6
    m.resolve_block_conflict(block5)  # new5

    expected = ["1", "2", "3", "new4", "new5", "new6"]
    assert [x["id"] for x in m.blocks] == expected
