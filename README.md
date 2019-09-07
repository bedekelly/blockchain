# Gossip

This is the start of a gossip protocol implementation. Using websockets, clients connect to each other and their details are shared to other clients on the network. Currently, the "flood" algorithm is used (where each client tells each other client about a new node on the network). However, the plan is to explore -- probably using docker containers to allow for `/etc/hosts` trickery -- how a more limited/random propagation algorithm performs on various network partitions.

In future when the algorithm is more stable, I'll probably define a binary format for messages between clients using the `struct` module; right now it's just using JSON to serialise dicts.