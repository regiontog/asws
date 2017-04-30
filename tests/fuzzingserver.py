import asyncio
import concurrent
import logging

from websocket.client import Client
from websocket.server import WebSocketServer
from websocket.stream.reader import WebSocketReader

logging.basicConfig(level=logging.WARNING,
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
            data = await socket.wait(reader.get(), 20)
            await socket.wait(client.writer.send(data), 20)
        except concurrent.futures._base.TimeoutError:
            raise
        except Exception as e:
            logger.warning(e)

with socket as server:
    logger.info(f'Serving on {server.sockets[0].getsockname()}')
    loop.run_forever()

loop.close()
