import sys
import ast
import random
import asyncio
import websockets
from threading import Thread
from contextlib import ExitStack


HOST = "0.0.0.0"
PORT = 1234 if"--gen" in sys.argv else random.randint(1025, 9999)
URLS = set()
PEER = None


_print = print
def print(*args, **kwargs):
    """Print out logs prepended with the port number."""
    return _print(f"[{PORT}]", *args, **kwargs)


async def server(websocket, path):
    """Respond to incoming websocket connections."""
    raw_data = await websocket.recv()
    data = ast.literal_eval(raw_data)
    if 'peer' in data:
        already_had = data['peer'] == f"ws://{HOST}:{PORT}" \
                      or data['peer'] in URLS
        await add_peer(data['peer'])
        msg = repr({"peers": list(URLS)})
        if not already_had:
            await propagate(data['peer'])
        if 'list_peers' in data:
            await websocket.send(msg)
    elif 'ping' in data:
        await websocket.send(repr({"pong": True}))
    else:
        reply = PEER.consume_message(data)
        if reply:
            await websocket.send(repr(reply))


async def propagate(peer):
    """Send this new peer to our other peers."""
    for url in list(URLS):
        if peer != url:
            print(f"Sending {peer} to {url}")
            async with websockets.connect(url) as connection:
                await connection.send(repr({"peer": peer}))


async def send_to_all(data):
    """Send arbitrary data to all connected peers."""
    for url in list(URLS):
        async with websockets.connect(url) as connection:
            await connection.send(repr(data))
                
            
async def add_peer(url):
    """Add a peer, provided it's online."""
    if HOST in url and str(PORT) in url:
        # Don't bother connecting to ourselves!
        return
    try:
        print("Adding new peer:", url)
        async with websockets.connect(url) as connection:
            await connection.send(repr({"ping": True}))
            data = ast.literal_eval(await connection.recv())
            if "pong" in data:
                print("Added new peer:", url)
                URLS.add(url)
    except Exception as e:
        print(e)

    
async def add_peers(urls):
    """Add all online peers to our list of connections."""
    for url in urls:
        if url not in list(URLS):
            await add_peer(url)
               

def new_client_msg():
    """Format the message to be sent when connecting afresh."""
    return repr({
        "peer": f"ws://{HOST}:{PORT}",
        "list_peers": True
    })


def get_random_peer():
    return random.choice(list(URLS))

    
async def update_peers():
    """Update our list of peers from another random peer."""
    updated = False
    while not updated:
        try:
            peer = get_random_peer()
            async with websockets.connect(peer) as connection:
                await connection.send(new_client_msg())
                data = ast.literal_eval(await connection.recv())
                await add_peers(data["peers"])
            updated = True
        except IndexError as e:
            if "--gen" not in sys.argv:
                raise e
            print("Genesis node doesn't have any peers. (OK)")
            updated = True
        except ConnectionRefusedError as e:
            print(f"Couldn't update from {peer}; removing.")
            URLS.remove(peer)
        
    
def load_initial_urls():
    with open("known_good.txt") as f:
        return [line.strip() for line in f.readlines()]


async def send_hello(url):
    """Connect to a peer and send a "hello" message."""
    async with websockets.connect(url) as connection:
        msg = repr({"msg": f"Hello from port {PORT}!"})
        await connection.send(msg)


def send_hello_to_peers():
    """Send a "hello" message to each connected peer."""
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while True:
        urls = list(URLS)  # Prevent set changing size.
        print("Sending hello to urls:", urls)
        for url in urls:
            try:
                asyncio.get_event_loop().run_until_complete(
                    send_hello(url))
            except ConnectionRefusedError as e:
                # Remove any peers which don't respond.
                print("Connection refused; "
                      "couldn't send hello to peer.", url, e)
                URLS.remove(url)
        import time; time.sleep(5)
    

async def request_from_random(request, callback):
    url = get_random_peer()
    async with websockets.connect(url) as connection:
        msg = repr(request)
        await connection.send(msg)
        reply = ast.literal_eval(await connection.recv())
        callback(reply)
    
        
def start_server(Peer):
    global URLS
    global PEER
    URLS = set(load_initial_urls())-set([f"ws://{HOST}:{PORT}"])
    PEER = Peer(send_to_all, request_from_random)

    # Start up the websocket server and request peer updates.
    start_server = websockets.serve(server, HOST, PORT)
    asyncio.get_event_loop().run_until_complete(start_server)
    asyncio.get_event_loop().run_until_complete(update_peers())
    
    # Start worker thread here for mining etc.
    PEER.start_worker()

    # Start websocket server here to respond to questions.
    print(f"Listening on port {PORT}")
    asyncio.get_event_loop().run_forever()
