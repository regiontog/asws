import asyncio
import concurrent
import logging

import os
import sys

root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, root)

from websocket.client import Client
from websocket.server import WebSocketServer
from websocket.stream.reader import WebSocketReader

logging.basicConfig(level=logging.DEBUG,
                    format=' %(levelname)s: %(name)s -- %(asctime)s.%(msecs)03d -- %(message)s',
                    datefmt='%H:%M:%S')

logger = logging.getLogger(__name__)

loop = asyncio.get_event_loop()
socket = WebSocketServer("localhost", 3001, loop=loop)


@socket.connection
async def on_connection(client: Client):
    logger.info(f'Connection from {client.addr, client.port}')
    logger.info(f'All clients: {socket.clients}')

    @client.message
    async def on_message(reader: WebSocketReader):
        try:
            await client.writer.feed(reader)
        except concurrent.futures._base.TimeoutError:
            raise
        except Exception as e:
            logger.warning(e)

with socket as server:
    logger.info(f'Serving on {server.sockets[0].getsockname()}')
    loop.run_forever()

loop.close()
