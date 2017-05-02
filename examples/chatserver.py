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


async def notify_of(client):
    await send_message(f'New client connected! {hex(id(client))}')

async def send_message(msg):
    for other in socket.clients.values():
        await other.writer.send(msg)


@socket.connection
async def on_connection(client: Client):
    print(f'Connection from {client.addr, client.port}')
    print(f'All clients: {socket.clients}')

    @client.message
    async def on_message(reader: WebSocketReader):
        await send_message(await reader.get())

    await notify_of(client)

with socket as server:
    print(f'Serving on {server.sockets[0].getsockname()}')
    loop.run_forever()

loop.close()
