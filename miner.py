import asyncio
import hashlib
import sys
import time
from collections import namedtuple, defaultdict, deque
from itertools import count, product, combinations, permutations
from threading import Thread
from uuid import uuid4 as uuid

import gossip
from hashing import cryptographic_hash
from signing import sign_transaction, generate_keypair, verify_transaction

# Make logs appear with a prepended port number.
log = gossip.log

UnspentTransaction = namedtuple("UnspentTransaction", "id amount address")


def add_hashes_to(blocks):
    yield from map(lambda b: {**b, "hash": cryptographic_hash(b)}, blocks)


def asyncio_run(fn):
    asyncio.get_event_loop().run_until_complete(fn)


def asyncio_background(fn):
    asyncio.ensure_future(fn)


def short_hash(block):
    """Return the first few characters from a block's hash."""
    hash_value = block.get("hash", cryptographic_hash(block))
    return str(hash_value)[:5]


def print_blockchain(blocks):
    length = len(blocks)
    short_hashes = map(short_hash, blocks[-5:])
    printable_chain = "<-".join(short_hashes)
    dots = "...<-" if length > 5 else ""
    log(f"Chain(length={length}, {dots}{printable_chain})")


def get_blockchain():
    """
    Format the message to request a blockchain from
    another node.
    """
    return {"request_blockchain": True}


def is_parent_of(block_one, block_two):
    """Returns True if block_one is parent of block_two, False otherwise."""
    return block_one["id"] == block_two["previous_block"]


class Miner(gossip.Peer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.unspent_transactions = {}
        self.current_transactions = []
        self.current_transaction_fees = 0
        self.blocks = []
        self.loser_blockchains = []
        self._difficulty = 15
        self.mining_reward = 1000
        self.got_new_block = False
        self.private_key, self.public_key = generate_keypair()
        printable_address = self.public_key[:10].decode("utf-8")
        log(f"Address: <{printable_address}...>")

    def update_blockchain(self, response):
        """
        Given a response from a peer containing a full blockchain C,
        set our own blockchain to C.
        """
        blocks = response["blocks"]
        for block in blocks:
            self.update_unspent_transactions_with_block(block)
            self.new_block(block)
        log("Updated blockchain.")
        self.print_chain()

    def update_unspent_transactions_with_block(self, block):
        """Update our unspent transactions pool."""
        trxid, amount, address = block["mine"]
        self.unspent_transactions[trxid] = UnspentTransaction(trxid, amount, address)

        for transaction in block["transactions"]:
            for transaction_input in transaction["inputs"]:
                # Todo: think carefully about the cases here.
                if transaction_input in self.unspent_transactions:
                    del self.unspent_transactions[transaction_input]

            for output in transaction["outputs"]:
                output_id, _, _ = output
                transaction = UnspentTransaction(*output)
                self.unspent_transactions[output_id] = transaction

    def handle_transaction_msg(self, transaction):
        """When sent a transaction, check it and add it to our next block."""
        if self.validate_transaction(transaction):
            log("Received valid transaction:", transaction)
            self.current_transactions.append(transaction)
            # Propagate it to our network
            asyncio_background(self.send_to_all(transaction))

    def validate_block(self, block):
        return (
            self.hash_complete(block)
            and block["previous_block_hash"] == self.previous_block_hash
            and self.validate_transactions(block["transactions"])
        )

    def coalesce_loser_blockchains(self):
        """
        Coalesce any pairs of chains into single chains, leaving the originals put.
        """
        for chain1, chain2 in permutations(self.loser_blockchains, r=2):
            if is_parent_of(chain1[-1], chain2[0]):
                self.loser_blockchains.append(chain1 + chain2)

    def add_to_losers(self, block):
        """
        Add a block to the loser blockchains.
        """
        for blockchain in list(self.loser_blockchains):
            start = blockchain[0]
            end = blockchain[-1]
            if is_parent_of(block, start):
                self.loser_blockchains.append(deque([block]) + blockchain)
            elif is_parent_of(end, block):
                self.loser_blockchains.append(blockchain + deque([block]))
        self.loser_blockchains.append(deque([block]))

    def resolve_block_conflict(self, block):
        """
        When we receive a block with a surprising parent ID, attempt to
        resolve the conflict and choose the longest blockchain fork.
        """
        # Form all possible new blockchains with the new block.
        self.add_to_losers(block)
        log(
            f"Conflicting block: {short_hash(block)}, "
            f"parent={str(block['previous_block_hash'])[:5]}"
        )
        self.coalesce_loser_blockchains()

        longest_loser_length = max(len(x) for x in self.loser_blockchains)
        if longest_loser_length > 2:
            pass

        # Given our new consolidated chains, try adding them to the blockchain.
        for blockchain in (b for b in self.loser_blockchains if len(b) > 1):
            fork_parent_id = blockchain[0]["previous_block"]
            fork_parent_index = self.find_block_by_id(fork_parent_id)
            if fork_parent_index is not None:
                self.swap_if_longer(blockchain, fork_parent_index)

    def find_block_by_id(self, block_id):
        """
        Return the index of the block with the given ID in our current blockchain,
        or None if we can't find that block ID.
        """
        for index, block in enumerate(self.blocks):
            if block["id"] == block_id:
                return index
        return None

    def swap_if_longer(self, blockchain, parent):
        """
        Given a candidate blockchain fork and the index of its parent,
        determine whether switching to that fork would yield a longer
        chain; then swap it out if so.
        """
        blocks_up_to_parent = self.blocks[: parent + 1]
        blocks_past_parent = self.blocks[parent + 1 :]
        if len(blockchain) > len(blocks_past_parent):
            self.blocks = blocks_up_to_parent + list(add_hashes_to(blockchain))
            self.loser_blockchains.append(deque(blocks_past_parent))
            self.loser_blockchains.remove(blockchain)

    @property
    def height(self):
        return len(self.blocks)

    def handle_block_msg(self, block):
        # Validate an incoming block message.
        if self.validate_block(block):
            self.update_unspent_transactions_with_block(block)
            self.new_block(block)
            self.got_new_block = True
            # asyncio_background(self.send_to_all(block))
            log("Updated with new block.")
            self.print_chain()

        elif self.hash_complete(block) and self.validate_transactions(
            block["transactions"]
        ):
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
        return print_blockchain(self.blocks)

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

            # Check each unspent transaction's output is the same as this
            # transaction's input.
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

    @property
    def previous_block_id(self):
        if self.blocks:
            return self.blocks[-1]["id"]
        return 0

    def mine_one_block(self):
        # Note: each sub-key needs to be hashable.
        fees = self.current_transaction_fees
        block = {
            "id": str(uuid()),
            "transactions": (),
            "mine": (str(uuid()), self.mining_reward + fees, self.address),
            "timestamp": int(time.time()),
            "previous_block": self.previous_block_id,
            "previous_block_hash": self.previous_block_hash,
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
