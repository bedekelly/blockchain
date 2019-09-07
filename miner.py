import gossip
import asyncio
from itertools import count
from threading import Thread


class Peer:
    def __init__(self, send_to_all):
        self.send_to_all = send_to_all

    def consume_message(self, msg):
        raise NotImplementedError("Peer.consume_message")


class Miner(Peer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.valid_transactions = []
    
    def consume_message(self, msg):
        print(msg)
        if 'transaction' in msg:
            valid = self.validate_transaction(msg['transaction'])
            if valid:
                self.valid_transactions.append(msg['transaction'])
        
    def mine_one_block(self):
        block = {
            transactions: self.valid_transactions,
            previous_block: self.previous_block_hash,
            nonce: 0
        }
    
        for i in count():
            block['nonce'] = i
            if self.cryptographic_hash(block) < self.difficulty:
                print("Block mined")
                break

    def cryptographic_hash(block):
        return hash(block)
    
    @property
    def difficulty(self):
        return 5
            
    def mine(self):
        # We're generally calling this inside a thread.
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        while True:
            asyncio.get_event_loop().run_until_complete(self.send_to_all({"data": "hi"}))
            import time; time.sleep(5)

    def start_worker(self):
        Thread(target=self.mine, daemon=True).start()

gossip.start_server(Miner)
