import asyncio
import hashlib
import sys
import time
from collections import namedtuple, defaultdict
from itertools import count
from threading import Thread
from uuid import uuid4 as uuid

import gossip
from hashing import cryptographic_hash
from signing import sign_transaction, generate_keypair

# Make logs appear with a prepended port number.
log = gossip.log

UnspentTransaction = namedtuple("UnspentTransaction", "id amount address")


def asyncio_run(fn):
    """Run a function in the current asyncio event loop."""
    asyncio.get_event_loop().run_until_complete(fn)


def short_hash(block):
    """Return the first few characters from a block's hash."""
    return str(block["hash"])[:5]


def get_blockchain():
    """
    Format the message to request a blockchain from
    another node.
    """
    return {"request_blockchain": True}


class Miner(gossip.Peer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.unspent_transactions = {}
        self.current_transactions = []
        self.current_transaction_fees = 0
        self.blocks = []
        self._difficulty = 10
        self.mining_reward = 1000
        self.got_new_block = False
        self.private_key, self.public_key = generate_keypair()
        printable_address = self.public_key[:10].decode("utf-8")
        log(f"Address: <{printable_address}...>")

        if "--gen" not in sys.argv:
            asyncio_run(
                self.request_from_random(get_blockchain(), self.update_blockchain)
            )

    def update_blockchain(self, response):
        blocks = response["blocks"]
        for block in blocks:
            self.update_unspent_transactions_with_block(block)
        self.print_unspent()

        # Todo: compare blockchains to choose the longer one.
        self.blocks = blocks
        log("Updated blockchain.")
        self.print_chain()

    def update_unspent_transactions_with_block(self, block):
        """Update our unspent transactions pool."""
        id, amount, address = block["mine"]
        self.unspent_transactions[id] = UnspentTransaction(id, amount, address)

        raise NotImplementedError("Update unspent trxs")

    def add_unspent_transaction(self, transaction):
        # Todo: validate signature
        # Todo: add new UnspentTransaction to our set.
        breakpoint()

    def handle_transaction_msg(self, data):
        valid = self.validate_transaction(data)
        if not valid:
            return
        for transaction in data:
            self.add_unspent_transaction(transaction)
            # Todo: propagate valid transactions

    def handle_block_msg(self, block):
        if self.hash_complete(block):
            # Todo: fork resolution & sanity checks.
            self.update_unspent_transactions_with_block(block)
            self.new_block(block)
            self.got_new_block = True
            # Todo: propagate valid blocks.
        else:
            log('Wrong hash on msg["block"]')
            breakpoint()

    def consume_message(self, msg):
        """Be a good Peer and respond to messages."""
        if "transaction" in msg:
            self.handle_transaction_msg(msg["transaction"])
        elif "request_blockchain" in msg:
            return {"blocks": self.blocks}
        elif "block" in msg:
            self.handle_block_msg(msg["block"])
        else:
            log("Unrecognised msg")
            breakpoint()

    def print_chain(self):
        """Print out a minified chain of block hashes."""
        length = len(self.blocks)
        short_hashes = map(short_hash, self.blocks)
        printable_chain = "<-".join(short_hashes)
        log(f"[{length}] {printable_chain}")

    def unspent(self):
        return repr(self.unspent_transactions)

    def balances(self):
        balances = defaultdict(int)
        for _, amount, to in self.unspent_transactions.values():
            balances[to.decode("utf-8")] += amount
        return balances

    def print_unspent(self):
        log("Unspent:", list(self.unspent_transactions.values()))

    def new_block(self, block):
        # Todo: this method assumes block is valid.
        self.blocks.append({**block, "hash": cryptographic_hash(block)})

    def mined_new_block(self, block):
        # Add the block to our blockchain.
        self.new_block(block)

        # Add the mining transaction to our unspent outputs.
        mine_id, amount, addr = block["mine"]
        mine_trx = UnspentTransaction(mine_id, amount, addr)
        self.unspent_transactions[mine_id] = mine_trx
        self.current_transaction_fees = 0
        self.current_transactions = []
        self.print_chain()

    def get_required_transactions(self, required):
        total = 0
        keys = set()
        for unspent in self.unspent_transactions.values():
            key, amount, address = unspent
            if address != self.address:
                continue
            total += amount
            keys.add(key)
            if total >= required:
                break
        return total, keys

    def add_outbound_transaction(self, data):
        """Add an outgoing transaction to the next block."""
        amount = sum(int(o["amount"]) for o in data["outputs"])
        fee = int(data.get("fee", 0))
        required = amount + fee
        total, keys = self.get_required_transactions(required)
        change = total - required

        formatted_outputs = [
            (str(uuid()), int(output["amount"]), str(output["address"]).encode("utf-8"))
            for output in data["outputs"]
        ]

        transaction = {
            "inputs": tuple(keys),
            "outputs": formatted_outputs,
            "change": change,
        }

        # Sign our transaction using our private key.
        signed_transaction = sign_transaction(transaction, self.private_key)

        # Now we add this to the next block.
        self.current_transactions.append(signed_transaction)

        # Todo: wait for some number of confirmations.
        for output in transaction["outputs"]:
            trx_id = output[0]
            self.unspent_transactions[trx_id] = output

        # Delete inputs from our unspent transactions pool.
        for input_ in keys:
            del self.unspent_transactions[input_]

        # Also keep track of how big our transaction fees are.
        self.current_transaction_fees += fee

        # Propagate this transaction to all nodes.
        asyncio_run(self.send_to_all(signed_transaction))

    def validate_transaction(self, transaction):
        # Note: we don't have to worry about transactions inside
        # one block interacting with each other. Later, we'll
        # require a certain number of confirmations before
        # transactions are accepted.
        breakpoint()
        return False

    def validate_transactions(self, transactions):
        return all(self.validate_transaction(t) for t in transactions)

    def mine_one_block(self):
        # Note: each subkey needs to be hashable.
        fees = self.current_transaction_fees
        block = {
            "transactions": (),
            "mine": (str(uuid()), self.mining_reward + fees, self.address),
            "timestamp": int(time.time()),
            "previous_block": self.previous_block_hash,
            "nonce": 0,
        }

        # Try to mine a block by incrementing the nonce.
        for block["nonce"] in count():
            # Exit early if we've got a new previous-block.
            if self.got_new_block:
                self.got_new_block = False
                return

            # Update our list of transactions.
            transactions = tuple(self.current_transactions)
            block["transactions"] = transactions

            # Update the reward with any new fees.
            uid, _, addr = block["mine"]
            fees = self.current_transaction_fees
            block["mine"] = (uid, self.mining_reward + fees, addr)

            # Check if we've successfully mined a block.
            if self.hash_complete(block):
                log("Mined new block.")
                self.mined_new_block(block)
                # Send our new block to every connected client.
                asyncio_run(self.send_to_all({"block": block}))
                break

    @property
    def address(self):
        # Todo: this should be a public key.
        return self.public_key

    @property
    def previous_block_hash(self):
        """Get the hash of the current last block."""
        if not self.blocks:
            return 0
        return self.blocks[-1]["hash"]

    def hash_complete(self, block):
        block_hash = cryptographic_hash(block)
        return block_hash < 1 << (512 - self._difficulty)

    @property
    def difficulty(self):
        return 2 << self._difficulty

    def mine(self):
        # Inside a thread, we need a new asyncio event loop.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        while True:
            self.mine_one_block()
            time.sleep(20)

    def start_worker(self):
        Thread(target=self.mine, daemon=True).start()


if __name__ == "__main__":
    gossip.Server(Miner).start()
