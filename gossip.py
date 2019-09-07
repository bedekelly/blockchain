import sys
import json
import random
import asyncio
import websockets
from threading import Thread
from contextlib import ExitStack


HOST = "0.0.0.0"
PORT = 1234 if"--gen" in sys.argv else random.randint(1025, 9999)
URLS = set()


async def server(websocket, path):
    raw_data = await websocket.recv()
    data = json.loads(raw_data)
    if 'peer' in data:
        already_had = data['peer'] == f"ws://{HOST}:{PORT}" \
                      or data['peer'] in URLS
        await add_peer(data['peer'])
        msg = json.dumps({"peers": list(URLS)})
        if not already_had:
            await propagate(data['peer'])
    if data.get('list_peers', False):
        await websocket.send(msg)
    elif 'ping' in data:
        await websocket.send(json.dumps({"pong": True}))
    elif 'msg' in data:
        print("Got message:", data['msg'])


async def propagate(peer):
    for url in iter(URLS):
        if peer != url:
            print(f"Sending {peer} to {url}")
            async with websockets.connect(url) as connection:
                await connection.send(json.dumps({"peer": peer}))

            
async def add_peer(url):
    if HOST in url and str(PORT) in url:
        # Don't bother connecting to ourselves!
        return
    try:
        print("Adding new peer:", url)
        async with websockets.connect(url) as connection:
            await connection.send(json.dumps({"ping": True}))
            data = json.loads(await connection.recv())
            print("Got data from peer", url, data)
            if "pong" in data:
                URLS.add(url)
    except Exception as e:
        print(e)

    
async def add_peers(urls):
    "Add all currently-alive peers to our list of connections."
    for url in urls:
        if url not in iter(URLS):
            await add_peer(url)
               

def new_client_msg():
    return json.dumps({
        "peer": f"ws://{HOST}:{PORT}",
        "list_peers": True
    })


def get_random_peer():
    return random.choice(list(URLS))

    
async def update_peers():
    try:
        peer = get_random_peer()
        async with websockets.connect(peer) as connection:
            await connection.send(new_client_msg())
            data = json.loads(await connection.recv())
            await add_peers(data["peers"])
    except IndexError:
        print("Genesis node doesn't have any peers. (OK)")
        
    
def load_initial_urls():
    with open("known_good.txt") as f:
        return [line.strip() for line in f.readlines()]


async def send_hello(url):
    async with websockets.connect(url) as connection:
        msg = json.dumps({"msg": f"Hello from port {PORT}!"})
        await connection.send(msg)


def send_hello_to_peers():
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    while True:
        for url in URLS:
            asyncio.get_event_loop().run_until_complete(send_hello(url))
        import time; time.sleep(5)
    

def initialise():
    global URLS
    URLS = set(load_initial_urls())-set([f"ws://{HOST}:{PORT}"])
    start_server = websockets.serve(server, HOST, PORT)
    print(URLS)

    asyncio.get_event_loop().run_until_complete(start_server)
    asyncio.get_event_loop().run_until_complete(update_peers())
    
    # Start worker thread here for mining etc.
    print("Thread starting: peers are:", URLS)
    t = Thread(target=send_hello_to_peers, daemon=True)
    t.start()

    print(f"Listening on port {PORT}")
    asyncio.get_event_loop().run_forever()
    t.join()


if __name__ == "__main__":
    initialise()


