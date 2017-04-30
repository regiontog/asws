import asyncio
import logging
import ssl

from .client import Client, HANDLERS
from .enums import State
from .http import handshake
from .reasons import Reasons
from .stream.reader import WebSocketReader

logger = logging.getLogger(__name__)


class WebsocketServer:
    NEWLINE = b'\r\n'

    def __init__(self, addr, port, certs=None, loop=None):

        if loop is None:
            self.loop = asyncio.get_event_loop()
        else:
            self.loop = loop

        self._on_connection = None
        self.addr = addr
        self.port = port
        self.server = None
        self.certs = certs
        self.clients = {}

    def __enter__(self):
        context = None
        if self.certs:
            crt, key = self.certs
            context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            context.load_cert_chain(certfile=crt, keyfile=key)

        coro = asyncio.start_server(self.socket_connect, self.addr, self.port, loop=self.loop, ssl=context)
        self.server = self.loop.run_until_complete(coro)
        return self.server

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.loop.run_until_complete(self.disconnect_all())
        self.server.close()
        self.loop.run_until_complete(self.server.wait_closed())

    def connection(self, fn):
        self._on_connection = fn

    async def connect_client(self, client):
        await self._on_connection(client)
        self.clients[client.addr, client.port] = client

    async def disconnect_all(self, timeout=1):
        done, pending = await asyncio.wait(map(self.disconnect_client, self.clients.values()), loop=self.loop,
                                           timeout=timeout)

        number_pending = len(pending)
        if number_pending > 0:
            logger.warning(f"{number_pending} futures failed to disconnect in {timeout} second(s), cancelling them.")
            for future in pending:
                future.cancel()

    async def disconnect_client(self, client, port=None):
        """If port is None try to disconnect client, else interpret client as the client address"""
        if port is not None:
            try:
                client = self.clients[client, port]
            except KeyError:
                return  # Client does not exist, nothing to to

        await client.close()
        del self.clients[client.addr, client.port]

    def delete_client(self, addr, port):
        try:
            del self.clients[addr, port]
        except KeyError:
            pass

    async def socket_connect(self, reader, writer):
        addr, port, *_ = writer.get_extra_info('peername')
        try:
            logger.debug(f"Client {addr, port} connected, attempting handshake.")
            state = await self.handle_handshake(reader, writer)

            if state != State.OPEN:
                logger.warning(f"Handshake with client {addr, port} failed.")
            else:
                logger.debug(f"Handshake with client {addr, port} successful.")
                client = Client(state, addr, port, writer, self.loop)
                self.loop.create_task(self.connect_client(client))

                while client.state != State.CLOSING:
                    client.read_task = self.loop.create_task(reader.readexactly(1))
                    try:
                        data = (await client.read_task)[0]
                        if data & WebSocketReader.RSV_BITS > 0:
                            logger.warning("No extension defining RSV meaning has been negotiated")
                            client.ensure_clean_close()
                            await client.close_with_read(reader, Reasons.PROTOCOL_ERROR.value, "RSV bit(s) set")
                            continue

                        # Find the correct handler based on the opcode
                        # Then pass it its arguments, including the fin flag
                        await HANDLERS[data & WebSocketReader.OP_CODE_BITS](client, reader,
                                                                            (data & WebSocketReader.FIN_BIT) != 0)
                    except asyncio.CancelledError:
                        continue  # Someone has cancelled the read task, check for new state
        except ConnectionResetError:
            logger.warning(f"Client {addr, port} has forcibly closed the connection.")
        except:
            raise
        finally:
            logger.debug(f"Closing connection with client {addr, port}.")
            writer.close()
            self.delete_client(addr, port)

    def wait(self, fut, timeout):
        return asyncio.wait_for(fut, timeout=timeout, loop=self.loop)

    async def handle_handshake(self, reader, writer):
        try:
            request_line = await self.wait(reader.readuntil(WebsocketServer.NEWLINE), 1)

            request = handshake.Request(request_line.decode())
            header = await self.wait(reader.readuntil(WebsocketServer.NEWLINE), 1)

            while header != WebsocketServer.NEWLINE:
                request.header(header.decode())
                header = await self.wait(reader.readuntil(WebsocketServer.NEWLINE), 1)

            response = request.validate_websocket_request()
            writer.write(response)
            return State.OPEN
        except handshake.BadRequestException:
            logger.exception("Failed to handshake.")
            writer.write(handshake.BadRequestException.RESPONSE)
            return State.CLOSING
        except (asyncio.streams.IncompleteReadError, asyncio.TimeoutError):
            logger.exception("Could not read stream, not http. Possibly https?.")
            writer.write(handshake.BadRequestException.RESPONSE)
            return State.CLOSING
        finally:
            await writer.drain()
