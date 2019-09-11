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
from signing import sign_transaction, generate_keypair, verify_transaction

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
        self.loser_blockchains = []
        self._difficulty = 20
        self.mining_reward = 1000
        self.got_new_block = False
        self.private_key, self.public_key = generate_keypair()
        printable_address = self.public_key[:10].decode("utf-8")
        log(f"Address: <{printable_address}...>")

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

        for transaction in block["transactions"]:
            for transaction_input in transaction["inputs"]:
                # Todo: think carefully about the cases here.
                if transaction_input in self.unspent_transactions:
                    del self.unspent_transactions[transaction_input]

            for output in transaction["outputs"]:
                output_id, _, _ = output
                self.unspent_transactions[output_id] = UnspentTransaction(*output)

    def handle_transaction_msg(self, transaction):
        """When sent a transaction, check it and add it to our next block."""
        if self.validate_transaction(transaction):
            log("Received valid transaction:", transaction)
            self.current_transactions.append(transaction)

    def validate_block(self, block):
        return (
            self.hash_complete(block)
            and block["previous_block"] == self.previous_block_hash
            and self.validate_transactions(block["transactions"])
        )

    def resolve_block_conflict(self, block):
        """
        When we receive a block with a surprising parent ID, attempt to
        resolve the conflict.

        Todo: handle SUB-FORKS:
            Our current blockchain is A->B->C->D->E
            We get a block F claiming B->F
            We get a block G claiming F->G
        So far so good: we've got F->G in our loser pool.
        Now we get a block H claiming F->H.
        In that case I think we should have a separate loser blockchain F->H in the loser pool.
        If we then get a block I claiming H->I, we can add I to BOTH loser blockchains.
        N.B. this means we'll have to check BOTH loser blockchains to see if they're now winners.

        Todo: think about what happens when loser blockchains claim an existing block in the winning blockchain.
        Todo: write good automated tests for all these situations.
        Todo: store our own block height; and keep track of the block height of loser forks.

        * Look back through our blockchain to see if its parent is an out-of-date node:
          + If so, check if it forms the start of a fork in our loser pool:
            + If not, keep it in its own new loser blockchain
            - If so, check if the fork is longer than our current one:
              + If so, swap in the new fork and put our fork into the "loser blockchains" pool
              + If not, leave the new fork in the loser pool
          + If not, check if it forms the start OR END of a fork in our loser pool:
            - If not, keep it in its own new loser blockchain
            - If so:
              + Append it to the start or end as appropriate
              + Check if the fork starts with a parent node which is in the current blockchain:
                - If so, check if the fork is longer than the current one:
                  + If so, swap the current fork into the loser pool
                  + If not, leave it in the loser pool
        """

        for reverse_index, old_block in enumerate(reversed(self.blocks)):

            if old_block["hash"] == block["previous_block"]:
                # Found the new block's parent.
                # Todo: each loser blockchain should store its proposed height.
                # Todo: we should keep track of our current block height.
                # Todo: that way, we can easily compare the two!
                self.loser_blockchains.append([block])
                break

        else:
            # Couldn't find the received block's parent anywhere; checking in loser blockchains.
            for blockchain in self.loser_blockchains:
                # Todo: All cases here.
                # Does this blockchain fit on the start or end of a loser blockchain?
                # If so, append it -- and then check if the resulting blockchain becomes a winner.
                raise NotImplementedError("Check if loser blockchain becomes a winner!")
            else:
                # Add our block as a new "loser blockchain"
                self.loser_blockchains.append([block])

    def handle_block_msg(self, block):
        # Validate an incoming block message.
        if self.validate_block(block):
            self.update_unspent_transactions_with_block(block)
            self.new_block(block)
            self.got_new_block = True
            # Todo: propagate valid blocks to peers.
            log("Updated with new block.")
            self.print_chain()

        elif self.hash_complete(block) and self.validate_transactions(block):

            # Note: this means only the previous block hash wasn't right;
            # it's still hashed correctly and each transaction is valid and signed.
            self.resolve_block_conflict(block)

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
        short_hashes = map(short_hash, self.blocks[-5:])
        printable_chain = "<-".join(short_hashes)
        dots = "...<-" if length > 5 else ""
        log(f"Chain(length={length}, {dots}{printable_chain})")

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
        # Note: current transactions should already have been added to our unspent transactions.
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
        else:
            raise ValueError("Insufficient Funds!")
        return total, keys

    def add_outbound_transaction(self, data):
        """Add an outgoing transaction to the next block."""

        # Calculate the correct amounts for the transaction.
        amount = sum(int(o["amount"]) for o in data["outputs"])
        fee = int(data.get("fee", 0))
        required = amount + fee
        try:
            total, keys = self.get_required_transactions(required)
        except ValueError as e:
            return {"error": "Insufficient funds!"}
        change = total - required

        # Generate the transaction outputs, including change.
        formatted_outputs = [
            (str(uuid()), int(output["amount"]), str(output["address"]).encode("utf-8"))
            for output in data["outputs"]
        ]
        formatted_outputs.append((str(uuid()), change, self.address))
        transaction = {
            "inputs": tuple(keys),
            "outputs": formatted_outputs,
            "from": self.address,
        }

        # Sign our transaction using our private key.
        signed_transaction = sign_transaction(transaction, self.private_key)

        # Now we add this to the next block.
        self.current_transactions.append(signed_transaction)

        # Delete inputs from our unspent transactions pool.
        for input_ in keys:
            del self.unspent_transactions[input_]

        # Also keep track of how big our transaction fees are.
        self.current_transaction_fees += fee

        # Add this transaction to our unspent transactions.
        for output in transaction["outputs"]:
            output_id, _, _ = output
            self.unspent_transactions[output_id] = output

        # Propagate this transaction to all nodes.
        asyncio_run(self.send_to_all({"transaction": signed_transaction}))

        # Return a success message to our client.
        return {"msg": "OK"}

    def validate_transaction(self, transaction):
        # Note: we don't have to worry about transactions inside
        # one block interacting with each other. Later, we'll
        # require a certain number of confirmations for inputs
        # before transactions are accepted.

        # First, check the cryptographic signature is correct.
        if not verify_transaction(transaction):
            return

        # Next check all outputs actually belong to the right address.
        input_transactions = []
        for input_id in transaction["inputs"]:

            # Check we have a record of every unspent transaction used.
            input_transaction = self.unspent_transactions.get(input_id, None)
            if input_transaction is None:
                return False

            # Check each unspent transaction's output is the same as this transaction's input.
            _, amount, address = input_transaction
            if address != transaction["from"]:
                return False

            # Build up a list of the input transactions used.
            input_transactions.append(input_transaction)

        # Check that the balance of the inputs and outputs is >=0.
        input_total = sum(t.amount for t in input_transactions)
        output_total = sum([t[1] for t in transaction["outputs"]])
        fee = input_total - output_total

        if fee < 0:
            print("Transaction declined since fee would be <0.")
            return False

        if any(t[1] <= 0 for t in transaction["outputs"]):
            print("Transaction with a <=0 output declined.")
            return False

        return True

    def validate_transactions(self, transactions):
        return all(self.validate_transaction(t) for t in transactions)

    def mine_one_block(self):
        # Note: each sub-key needs to be hashable.
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

        if "--gen" not in sys.argv:
            asyncio_run(
                self.request_from_random(get_blockchain(), self.update_blockchain)
            )

        while True:
            self.mine_one_block()
            # time.sleep(5)

    def start_worker(self):
        Thread(target=self.mine, daemon=True).start()


if __name__ == "__main__":
    gossip.Server(Miner).start()
