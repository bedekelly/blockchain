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
        self._difficulty = 25
        self.got_new_block = False
        
        if "--gen" not in sys.argv:
            asyncio_run(self.request_from_random(
                get_blockchain(),
                self.update_blockchain
            ))

    def update_blockchain(self, response):
        blocks = response['blocks']
        for block in blocks:
            self.update_unspent_transactions_with_block(block)
        self.print_unspent()
        
        # Todo: compare blockchains to choose the longer one.
        self.blocks = blocks
        print("Updated blockchain.")
        self.print_chain()

    def update_unspent_transactions_with_block(self, block):
        """Update our unspent transactions pool."""
        transactions = block['transactions']
        update_unspent_transactions(
            self.unspent_transactions, transactions)
        self.print_unspent()

    def handle_transactions_msg(data):
        valid = self.validate_transactions_message(data)
        if not valid:
            return
        for transaction in data:
            self.update_transactions(transaction)
            # Todo: propagate valid transactions

    def handle_block_msg(block):
        if self.hash_complete(msg["block"]):
            # Todo: fork resolution & sanity checks.
            self.new_block(msg["block"])
            self.got_new_block = True
            # Todo: propagate valid blocks.
        else:
            print("Wrong hash on msg[\"block\"]")
            breakpoint()

    def consume_message(self, msg):
        """Be a good Peer and respond to messages."""
        if "transactions" in msg:
            self.handle_transactions_msg(msg['transactions'])
        elif "request_blockchain" in msg:
            return {"blocks": self.blocks}
        elif "block" in msg:
            self.handle_block_msg(msg['block'])
        else:
            print("Unrecognised msg")
            breakpoint()

    def print_chain(self):
        length = len(self.blocks)
        short_hash = lambda block: str(block['hash'])[:5]
        short_hashes = map(short_hash, self.blocks)
        printable_chain = '<-'.join(short_hashes)
        print(f"[{length}] {printable_chain}") 

    def print_unspent(self):
        print("Unspent:", list(
            self.unspent_transactions.values()))
        
    def new_block(self, block):
        self.update_unspent_transactions_with_block(block)
        self.blocks.append({
            **block,
            "hash": self.cryptographic_hash(block)
        })
        self.print_chain()

    def add_transaction(self, transaction):
        # Todo: find a list of inputs for the given amount.
        # Each input is an unspent transaction whose output
        # was the address we're using.
        
        # Inputs is a list of unspent transaction IDs.
        # Outputs is a list of (address, amount) pairs.
        # The outputs plus change should sum to less than
        # or equal to the inputs.
        # The difference is added on to the mining trx.
        
        transaction = {
            "inputs": (),
            "outputs": (),
            "change": ""
        }

        # Sign our transaction using our public key.
        signed_transaction = sign_transaction(transaction)

        # Now we add this to the next block.
        self.current_transactions.append(signed_transaction)

        # Also keep track of how big our transaction fees are.
        fee = sum(inputs) - sum(outputs) - change
        self.transaction_fees += fee
        
    def validate_transaction(self, transaction):
        breakpoint()
        
    def validate_transactions_message(self, transactions):
        return all(self.validate_transaction(t)
                   for t in transactions)

    def mine_one_block(self):
        # Note: each subkey needs to be hashable.
        block = {
            'transactions': (
                *self.current_transactions,
                 ("mine", (
                     (uuid().hex,
                      # Todo: mining reward + trx_fees
                      self.mining_reward,
                      self.address),
                 ))
            ),
            'timestamp': int(time.time()),
            'previous_block': self.previous_block_hash,
            'nonce': 0
        }

        # Try to mine a block by incrementing the nonce.
        for block['nonce'] in count():
            # Exit early if we've got a new previous-block.
            if self.got_new_block:
                self.got_new_block = False
                return
            # Check if we've successfully mined a block.
            if self.hash_complete(block):
                print("Mined new block.")
                self.new_block(block)
                # Send our new block to every connected client.
                asyncio_run(self.send_to_all({"block":block}))
                break

    @property
    def address(self):
        # Todo: this should be a public key.
        return gossip.PORT
            
    @property
    def previous_block_hash(self):
        """Get the hash of the current last block."""
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


if __name__ == "__main__":
    gossip.start_server(Miner)
