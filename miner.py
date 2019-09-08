import re
import sys
import time
from uuid import uuid4 as uuid
import gossip
import hashlib
from gossip import print
import asyncio
from itertools import count
from threading import Thread


def asyncio_run(fn):
    asyncio.get_event_loop().run_until_complete(fn)


class Peer:
    def __init__(self, send_to_all, request_from_random):
        self.send_to_all = send_to_all
        self.request_from_random = request_from_random

    def consume_message(self, msg):
        raise NotImplementedError("Peer.consume_message")


def get_blockchain():
    return {
        "request_blockchain": True
    }


def update_unspent_transactions(unspent, new_transactions):
    # N.B. At this point we're assuming the block is signed.
    mined = False
    new_keys = {}
    for (trx_type, trx_data) in new_transactions:
        if trx_type == "mine":
            if mined:
                print("Warning: double mining attempted.")
                return

            outputs = trx_data

            # Todo: pass in mining reward amount.
            ids, amounts, addresses = zip(*outputs)
            total_amount = sum(amounts)
            if total_amount != 1000:
                print("Warning: mining reward not correct.")
                return

            # Todo: Check id isn't already used.
            for trx_id, amount, address in outputs:
                if trx_id in {**unspent, **new_keys}:
                    print("Warning: ID already used.")
                    return
                amount = int(amount)
                new_keys[trx_id] = (amount, address)
            mined = True
    unspent.update(new_keys)

    
class Miner(Peer):

    mining_reward = 1000
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.unspent_transactions = {}
        self.current_transactions = []
        self.blocks = []
        self._difficulty = 21
        self.got_new_block = False
        if "--gen" not in sys.argv:
            asyncio_run(self.request_from_random(
                get_blockchain(),
                self.update_blockchain
            ))

    def update_blockchain(self, response):
        blocks = response['blocks']

        # Save the old blockchain.
        old_blocks = self.blocks
        # First, iterate through the blocks and get a set of
        # unspent transaction outputs.
        for block in blocks:
            self.update_unspent_transactions_with_block(block)

        # Todo: compare blockchains to choose the longer one.
        self.blocks = blocks
        print("Updated blockchain.")
        self.print_chain()

    def update_unspent_transactions_with_block(self, block):
        """Update our unspent transactions pool."""
        unspent = {}
        transactions = block['transactions']
        update_unspent_transactions(unspent, transactions)
        self.unspent_transactions.update(unspent)

    def consume_message(self, msg):
        """Be a good Peer and respond to messages."""
        if "transactions" in msg:
            data = msg['transactions']
            valid = self.validate_transactions_message(data)
            if valid:
                for transaction in data:
                    self.update_transactions(transaction)
                # Todo: propagate valid transactions.
        elif "request_blockchain" in msg:
            return {"blocks": self.blocks}
        elif "block" in msg:
            if self.hash_complete(msg["block"]):
                self.new_block(msg["block"])
                self.got_new_block = True
                # Todo: propagate valid blocks.
            else:
                print("Wrong hash on msg[\"block\"]")
                breakpoint()
        else:
            print("Unrecognised msg")
            breakpoint()


    def print_chain(self):
        length = len(self.blocks)
        chain = '<-'.join(
            str(block['hash'])[:5] for block in self.blocks)
        print(f"[{length}] {chain}") 
        
    def new_block(self, block):
        self.update_unspent_transactions_with_block(block)
        self.blocks.append({
            **block,
            "hash": self.cryptographic_hash(block)
        })
        self.print_chain()

    def validate_transaction(self, transaction):
        breakpoint()
        
    def validate_transactions_message(self, transactions):
        return all(self.validate_transaction(t)
                   for t in transactions)

    def mine_one_block(self):
        mining_trx = ("mine", (
                (uuid().hex, self.mining_reward, self.address),
            )
        )
        block = {
            'transactions': (
                *self.current_transactions,
                 mining_trx
            ),
            'timestamp': int(time.time()),
            'previous_block': self.previous_block_hash,
            'nonce': 0
        }
    
        for i in count():
            if self.got_new_block:
                self.got_new_block = False
                return
            block['nonce'] = i
            if self.hash_complete(block):
                print("Mined new block.")
                self.new_block(block)
                asyncio_run(self.send_to_all({"block":block}))
                break

    @property
    def address(self):
        return gossip.PORT
            
    @property
    def previous_block_hash(self):
        if not self.blocks:
            return 0
        return self.blocks[-1]["hash"]

    def cryptographic_hash(self, block):
        hash_input = repr(list(sorted(block.items())))
        hash_input = hash_input.encode("utf-8")
        # Todo: can I just get the integer instead of a string?
        hash_value = hashlib.sha512(hash_input).hexdigest()
        hash_num = int(f"0x{hash_value}", 16)
        return hash_num

    def hash_complete(self, block):
        block_hash = self.cryptographic_hash(block)
        return block_hash < 1<<(512 - self._difficulty)
    
    @property
    def difficulty(self):
        return 2 << self._difficulty

    def mine(self):
        # Inside a thread, we need a new asyncio event loop.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        while True:
            self.mine_one_block()

    def start_worker(self):
        Thread(target=self.mine, daemon=True).start()

gossip.start_server(Miner)
