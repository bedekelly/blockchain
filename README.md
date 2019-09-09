# Blockchain from First Principles

This is a blockchain and cryptocurrency system written from scratch in Python. The point is to learn about how cryptocurrencies actually work, and solve the problems that get glossed over in introductory tutorials: peering, data format, multithreaded code, merkle tree formation and so on.

Although the cryptocurrency is implemented on top to incentivise nodes, this isn't intended for trading or use as currency; it'll probably be really insecure because I'm not an expert at writing cryptographic software.


### API

An HTTP API is exposed for sensitive functionality like creating signed transactions from the node's private key. Of course this isn't the sort of thing that should be exposed to the web! But it is handy for local testing, and the idea is to secure this by some sort of user account per-node.

This code is in [`private_api.py`](./private_api.py).


### Mining
A block is comprised of a timestamp, the hash of the previous node in the blockchain, a block of transactions (including one "mine" transaction), and a "nonce": an arbitrary number chosen by the miner. This number is changed repeatedly, until the hash of the entire block is less than some predetermined amount. (This is affected by the mining difficulty.

Since a transaction's inputs are expressed as a list of input transaction IDs, and these IDs are guaranteed to be unique, there is no danger of double-spending -- once a transaction's outputs are spent, nodes remove them from the unspent transaction pool and don't recognise any further attempts to spend those coins.

The code for mining is in [`miner.py`](./miner.py).


### Cryptography

Block hashing uses SHA512. There aren't currently any reports of this algorithm having been broken.

There's no distinction between a user's public key and their "address" in this system; to send coins to a user  means youu must have their public key. I haven't yet found any cryptographic rationale behind obscuring a public key, beyond the idea that shorter keys are easier to type.

For signing transactions, the PyNaCl library is used, which is a binding to libsodium. The algorithm used for signing/verifying messages is Ed25519, which is the state of the art for fast signing with a high security level. The signing bit of this code is extremely simple, which is a good thing!

The code for this isn't finished but some stub functionality is in [`signing.py`](./signing.py).


### Peering and Discovery

This is the start of a gossip protocol implementation. Using websockets, clients connect to each other and their details are shared to other clients on the network. Currently, the "flood" algorithm is used (where each client tells each other client about a new node on the network). However, the plan is to explore -- probably using docker containers to allow for `/etc/hosts` trickery -- how a more limited/random propagation algorithm performs on various network partitions.

In future when the algorithm is more stable, I'll probably define a binary format for messages between clients using the `struct` module; right now it's just using "PyON" (`repr()` and `ast.literal_eval()`) to serialise dicts. The constant hashing of data types makes `json`'s default behaviour of deserialising to lists -- an unhashable type -- less than useful.

The code for the peering is in [`gossip.py`](./gossip.py).