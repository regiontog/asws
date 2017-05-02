import asyncio

import os
import sys

root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, root)

from websocket.client import Client
from websocket.server import WebSocketServer
from websocket.stream.reader import WebSocketReader

loop = asyncio.get_event_loop()
socket = WebSocketServer("localhost", 3001, loop=loop)


@socket.connection
async def on_connection(client: Client):
    print(f'Connection from {client.addr, client.port}')
    print(f'All clients: {socket.clients}')

    @client.message
    async def on_message(reader: WebSocketReader):
        await client.writer.feed(reader)

with socket as server:
    print(f'Serving on {server.sockets[0].getsockname()}')
    loop.run_forever()

loop.close()
