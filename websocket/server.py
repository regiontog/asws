"""Usage

>>> loop = asyncio.get_event_loop()
>>> socket = WebSocketServer("localhost", 3001, loop=loop)
...
>>> @socket.connection
>>> async def on_connection(client: Client):
...     logger.info(f'Connection from {client.addr, client.port}')
...     logger.info(f'All clients: {socket.clients}')
...
...     @client.message
...     async def on_message(reader: WebSocketReader):
...         await client.writer.send(await reader.get())
...
>>> with socket as server:
...     print(f'Serving on {server.sockets[0].getsockname()}')
...     loop.run_forever()
...
>>> loop.close()
"""

import asyncio
import logging
import ssl

import time

from .client import Client, HANDLERS
from .enums import State
from .http import handshake
from .reasons import Reasons
from .stream.reader import WebSocketReader

logger = logging.getLogger(__name__)


class WebSocketServer:
    """
    :ivar addr: The server IPv4 or IPv6 address.
    :type addr: str
    :ivar port: The server port.
    :type port: int
    :ivar timeout: The timeout in seconds for clients, if they don't respond to pings. Set to 0 to disable heartbeat.
    :type timeout: float
    :ivar certs: SSL certificates
    :type certs: (certfile, keyfile)
    :ivar clients: All of the connected clients.
    :type clients: {(str, int): Client}
    :ivar loop: The event loop to run in.
    :type loop: AbstractEventLoop 
    """
    NEWLINE = b'\r\n'

    def __init__(self, addr, port, certs=None, loop=None, timeout=120):
        if loop is None:
            self.loop = asyncio.get_event_loop()
        else:
            self.loop = loop

        self._on_connection = None
        self.addr = addr
        self.port = port
        self.server = None
        self.certs = certs
        self.client_timeout = timeout
        self.clients = {}
        self.keepalive_task = None

    async def keepalive(self, timeout):
        try:
            half = int(timeout / 2)
            while True:
                await asyncio.sleep(half, loop=self.loop)
                logger.info("Sending heartbeats")
                cur_time = time.time()

                for client in self.clients.values():
                    diff = cur_time - client.last_message
                    if diff > timeout:
                        logger.warning(f"Cleaning up non-responsive client {client.addr, client.port}")
                        self.disconnect_client(client, code=Reasons.POLICY_VIOLATION.value.code,
                                               reason='Client did not respond to heartbeat.')

                    elif diff > half:
                        client.writer.ping('heartbeat')

        except asyncio.CancelledError:
            pass

    def __enter__(self):
        """Start the server when entering the context manager."""
        context = None
        if self.certs:
            crt, key = self.certs
            context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            context.load_cert_chain(certfile=crt, keyfile=key)

        coro = asyncio.start_server(self.socket_connect, self.addr, self.port, loop=self.loop, ssl=context)
        self.server = self.loop.run_until_complete(coro)
        if self.client_timeout > 0:
            self.keepalive_task = self.loop.create_task(self.keepalive(self.client_timeout))

        return self.server

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop server when exiting context manager"""
        if self.keepalive_task is not None:
            self.keepalive_task.cancel()

        self.loop.run_until_complete(self.disconnect_all())
        self.server.close()
        self.loop.run_until_complete(self.server.wait_closed())

    def connection(self, fn):
        """Decorator for registering the on_connection callback.
        
        :param fn: The callback to register.
        
        The callback should be async and take one parameter, :class:`~websocket.client.Client`.
        This callback is called when a new client connects with the websocket.

        >>> @socket.connection
        >>> async def on_connection(client: Client):
        ...     for other_client in socket.clients.vals():
        ...         other_client.writer.send("New client connected.")
        ...     
        ...     @client.message
        ...     async def on_message(reader: WebSocketReader):
        ...         await client.writer.send(await reader.get())
        """
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

    async def disconnect_client(self, client, code=Reasons.NORMAL.value.code, reason=''):
        """This method is the only clean way to close a connection with a client.
        
        >>> @socket.connection
        >>> async def on_connection(client: Client):
        ...     print("Client connected, disconnecting it...")
        ...     socket.disconnect_client(client)

        :param client: The client to disconnect from the server.
        :param code: The code to close the connection with, make sure it is valid. Default is :attr:`websocket.reasons.Reasons.NORMAL.value.code`
        :type code: bytes
        :param reason: The reason for closing the connection, may be ''. Should not be longer than 123 characters.
        :type reason: str
        """
        await client.close(code, reason)
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
                        client.tick()
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
        """Helper method for creating a future that times out after a timeout.
        
        :param fut: The future to time.
        :param timeout: The timeout in seconds.
        
        :return: future
        """
        return asyncio.wait_for(fut, timeout=timeout, loop=self.loop)

    async def handle_handshake(self, reader, writer):
        try:
            request_line = await self.wait(reader.readuntil(WebSocketServer.NEWLINE), 1)

            request = handshake.Request(request_line.decode())
            header = await self.wait(reader.readuntil(WebSocketServer.NEWLINE), 1)

            while header != WebSocketServer.NEWLINE:
                request.header(header.decode())
                header = await self.wait(reader.readuntil(WebSocketServer.NEWLINE), 1)

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
