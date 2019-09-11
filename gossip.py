import ast
import asyncio
import random
import sys
import time

import websockets

from private_api import Api

HOST = "0.0.0.0"
PORT = 1234 if "--gen" in sys.argv else random.randint(1026, 9999)


def log(*args, **kwargs):
    """Print out logs prepended with the port number."""
    return print(f"[{PORT}]", *args, **kwargs)


class Peer:
    """
    Abstract base class defining which methods a node must
    implement to connect to other nodes.
    """

    def __init__(self, send_to_all, request_from_random):
        self.send_to_all = send_to_all
        self.request_from_random = request_from_random

    def consume_message(self, msg):
        raise NotImplementedError("Peer.consume_message")


class Server:
    def __init__(self, create_worker):
        self.worker = None
        self.worker = create_worker(self.send_to_all, self.request_from_random)
        self.urls = set(self.load_initial_urls()) - {f"ws://{HOST}:{PORT}"}

    async def server(self, websocket, path):
        """Respond to incoming websocket connections."""
        raw_data = await websocket.recv()
        data = ast.literal_eval(raw_data)
        if "peer" in data:
            already_had = (
                data["peer"] == f"ws://{HOST}:{PORT}" or data["peer"] in self.urls
            )
            await self.add_peer(data["peer"])
            msg = repr({"peers": list(self.urls)})
            if not already_had:
                await self.propagate(data["peer"])
            if "list_peers" in data:
                await websocket.send(msg)
        elif "ping" in data:
            await websocket.send(repr({"pong": True}))
        else:
            reply = self.worker.consume_message(data)
            if reply:
                await websocket.send(repr(reply))

    async def propagate(self, peer):
        """Send this new peer to our other peers."""
        for url in list(self.urls):
            if peer != url:
                log(f"Sending {peer} to {url}")
                async with websockets.connect(url) as connection:
                    await connection.send(repr({"peer": peer}))

    async def send_to_all(self, data):
        """Send arbitrary data to all connected peers."""
        for url in list(self.urls):
            try:
                async with websockets.connect(url) as connection:
                    await connection.send(repr(data))
            except ConnectionRefusedError:
                self.urls.remove(url)

    async def add_peer(self, url):
        """Add a peer, provided it's online."""
        if HOST in url and str(PORT) in url:
            # Don't bother connecting to ourselves!
            return
        try:
            log("Adding new peer:", url)
            async with websockets.connect(url) as connection:
                await connection.send(repr({"ping": True}))
                data = ast.literal_eval(await connection.recv())
                if "pong" in data:
                    log("Added new peer:", url)
                    self.urls.add(url)
        except Exception as e:
            log(e)

    async def add_peers(self, urls):
        """Add all online peers to our list of connections."""
        for url in urls:
            if url not in list(self.urls):
                await self.add_peer(url)

    @staticmethod
    def new_client_msg():
        """Format the message to be sent when connecting afresh."""
        return repr({"peer": f"ws://{HOST}:{PORT}", "list_peers": True})

    def get_random_peer(self):
        try:
            return random.choice(list(self.urls))
        except IndexError:
            return None

    async def update_peers(self):
        """Update our list of peers from another random peer."""
        updated = False
        while not updated:
            peer = self.get_random_peer()
            if peer is None:
                if "--gen" not in sys.argv:
                    raise ValueError("Non-genesis node can't find any peers.")
                log("Genesis node doesn't have any peers. (OK)")
                return

            try:
                async with websockets.connect(peer) as connection:
                    await connection.send(self.new_client_msg())
                    data = ast.literal_eval(await connection.recv())
                    await self.add_peers(data["peers"])
                updated = True
            except ConnectionRefusedError:
                log(f"Couldn't update from {peer}; removing.")
                self.urls.remove(peer)

    @staticmethod
    def load_initial_urls():
        with open("known_good.txt") as f:
            return [line.strip() for line in f.readlines()]

    @staticmethod
    async def send_hello(url):
        """Connect to a peer and send a "hello" message."""
        async with websockets.connect(url) as connection:
            msg = repr({"msg": f"Hello from port {PORT}!"})
            await connection.send(msg)

    def send_hello_to_peers(self):
        """Send a "hello" message to each connected peer."""
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while True:
            urls = list(self.urls)  # Prevent set changing size.
            log("Sending hello to urls:", urls)
            for url in urls:
                try:
                    asyncio.get_event_loop().run_until_complete(self.send_hello(url))
                except ConnectionRefusedError as e:
                    # Remove any peers which don't respond.
                    log("Connection refused; couldn't send hello to peer.", url, e)
                    self.urls.remove(url)
            time.sleep(5)

    async def request_from_random(self, request, callback):
        url = self.get_random_peer()
        async with websockets.connect(url) as connection:
            msg = repr(request)
            await connection.send(msg)
            reply = ast.literal_eval(await connection.recv())
            callback(reply)

    def start(self):
        # Start up the websocket server and request peer updates.
        start_server = websockets.serve(self.server, HOST, PORT)
        asyncio.get_event_loop().run_until_complete(start_server)
        asyncio.get_event_loop().run_until_complete(self.update_peers())

        # Start worker thread here for mining etc.
        self.worker.start_worker()

        # Start Flask server for private API
        Api(PORT + 1, self.worker).run()

        # Start websocket server here to respond to questions.
        log(f"Listening on port {PORT}")
        asyncio.get_event_loop().run_forever()
