"""
You should not make an instance of the Client class yourself, rather you should listen for new connections with 
:meth:`~websocket.server.WebSocketServer.connection`

>>> @socket.connection
>>> async def on_connection(client: Client):
...     # Here you can use the client, register callbacks on it or send it messages
...     await client.writer.ping()
"""
import asyncio
import logging

from .enums import DataType, State
from .reasons import Reasons, Reason
from .stream.reader import WebSocketReader
from .stream.writer import WebSocketWriter

logger = logging.getLogger(__name__)


class Client:
    """
    :ivar addr: IPv4 or IPv6 address of the client.
    :type addr: str
    :ivar port: The port the client opened it's socket on.
    :type port: int
    :ivar writer: The writer used for writing frames to the client.
    :type writer: WebSocketWriter
    """

    def __init__(self, state, addr, port, writer, loop):
        self.state = state
        self.addr = addr
        self.port = port
        self.data_type = DataType.NONE
        self.writer = WebSocketWriter(writer, loop)
        self._reader = None
        self.read_task = None
        self.continuation = DataType.NONE
        self.server_has_initiated_close = False
        self._loop = loop

        @self.message
        async def on_message(reader):
            raise Exception("No message callback defined.")

        @self.ping
        async def on_ping(payload, length):
            await self.writer.pong(length, payload)

        @self.pong
        async def on_pong(payload, length):
            pass

        @self.closed
        async def on_closed(code, reason):
            pass

    def message(self, fn):
        """Decorator for registering the on_message callback.
        
        :param fn: The callback to register.
        
        The callback should be async and take one parameter, a :class:`~websocket.stream.reader.WebSocketReader`
        
        This callback is called when the server receives an valid data frame, 
        if an exception occurs after the first valid frame e.g. if an text frame 
        contains invalid utf-8, or if it's an invalid fragmented message, then we 
        send the exception to the reader with :meth:`~asyncio.StreamReader.set_exception`.
        
        >>> @client.message
        >>> async def on_message(reader: WebSocketReader):
        ...     print("Got message " + await reader.get())
        """
        self.on_message = fn

    def ping(self, fn):
        """Decorator for registering the on_ping callback.
        
        :param fn: The callback to register.
        
        If you set this callback you will override the default behaviour of sending pongs back to the client when 
        receiving pings. If you want to keep this behaviour call :meth:`~websocket.stream.writer.WebSocketWriter.pong`.
        
        The callback should be async and take two parameters, :class:`bytes` payload, and :class:`int` length.
        This callback is called when we receive a valid ping from the client.
        
        >>> @client.ping
        >>> async def on_ping(payload: bytes, length: int):
        ...     print("Received ping from client")
        ...     await self.writer.pong(length, payload)
        """
        self.on_ping = fn

    def pong(self, fn):
        """Decorator for registering the on_pong callback.
        
        :param fn: The callback to register.
        
        The callback should be async and take two parameters, :class:`bytes` payload, and :class:`int` length
        This callback is called when we receive a valid pong from the client.

        >>> @client.pong
        >>> async def on_pong(payload: bytes, length: int):
        ...     print("Received pong from client")
        """
        self.on_pong = fn

    def closed(self, fn):
        """Decorator for registering the on_closed callback.
        
        :param fn: The callback to register.
        
        The callback should be async and take two parameters, :class:`bytes` code of length 2, and :class:`str` reason.
        This callback is called when the connection this this client is closing.

        >>> @client.closed
        >>> async def on_closed(code: bytes, reason: str):
        ...     print("Connection with client is closing for " + reason)
        """
        self.on_closed = fn

    async def close_with_read(self, reader, code, reason):
        close = asyncio.ensure_future(self.close(code, reason), loop=self._loop)
        buffer = WebSocketReader(DataType.BINARY, self, self._loop)
        length = await buffer.feed(reader)
        buffer.done()
        logger.debug("1")
        data = await buffer.read(length)
        logger.debug("2")
        await close
        return data

    async def close(self, code: bytes, reason: str):
        if not self.server_has_initiated_close:
            asyncio.ensure_future(self.on_closed(code, reason), loop=self._loop)
            self.server_has_initiated_close = True
            await self.writer.close(code, reason)

            # TODO: Kill in 5 secs if client dont respond

    async def _read_message(self, reader, fin):
        await self._reader.feed(reader)

        if fin:
            self.continuation = DataType.NONE
            self._reader.done()
        else:
            self.continuation = self._reader.data_type

    @staticmethod
    def handle_data(kind):
        async def handler(self, reader, fin):
            if self.continuation != DataType.NONE:
                self._reader.set_exception(Exception(
                    f"Received unexpected {kind.name.lower()} data frame from client {self.addr, self.port}, "
                    "expected continuation."))

                self._reader.done()
                await self.close_with_read(reader, Reasons.PROTOCOL_ERROR.value, "expected continuation frame")
                return

            logger.debug(f"Received {kind.name.lower()} data frame from client {self.addr, self.port}.")
            self.type = kind
            self._reader = WebSocketReader(kind, self, self._loop)
            self._loop.create_task(self.on_message(self._reader))

            return await self._read_message(reader, fin)

        return handler

    async def handle_continuation(self, reader, fin):
        if self.continuation == DataType.NONE:
            logger.debug("Received unexpected continuation data frame from client "
                         f"{self.addr, self.port}, expected {self.continuation.name.lower()}.")

            await self.close_with_read(reader, Reasons.PROTOCOL_ERROR.value,
                                       f"expected {self.continuation.name.lower()} frame")
            return

        logger.debug(f"Received continuation frame from client {self.addr, self.port}.")
        await self._read_message(reader, fin)

    def ensure_clean_close(self):
        if self.continuation != DataType.NONE:
            self._reader.set_exception(Exception("Closing connection in middle of message."))
            self._reader.done()

    @staticmethod
    def handle_ping_or_pong(kind):
        async def handler(self, reader, fin):
            buffer = WebSocketReader(DataType.BINARY, self, self._loop)
            feed = asyncio.ensure_future(buffer.feed_once(reader), loop=self._loop)

            if not fin or self.server_has_initiated_close:
                if not fin:
                    logger.warning(f"Received fragmented {kind.name.lower()} from client {self.addr, self.port}.")
                    self.ensure_clean_close()
                    await self.close(Reasons.PROTOCOL_ERROR.value, "fragmented control frame")
                else:
                    logger.warning(f"Received {kind.name.lower()} from client {self.addr, self.port} after server "
                                   "initiated close.")
                    self.ensure_clean_close()
                    await self.close(Reasons.POLICY_VIOLATION.value, "control frame after close")

                await feed
                return

            length = await feed
            if length > 125:
                logger.warning(f"{kind.name.lower()} payload too long({length} bytes).")
                self.ensure_clean_close()
                await self.close(Reasons.PROTOCOL_ERROR.value, "control frame too long")
                return

            logger.debug(f"Received {kind.name.lower()} from client {self.addr, self.port}.")
            data = await buffer.read(length)
            if kind is DataType.PING:
                self._loop.create_task(self.on_ping(data, length))
            elif kind is DataType.PONG:
                self._loop.create_task(self.on_pong(data, length))

            buffer.done()
        return handler

    async def handle_close(self, reader, fin):
        logger.debug(f"Received close from client {self.addr, self.port}.")

        buffer = WebSocketReader(DataType.BINARY, self, self._loop)
        length = await buffer.feed_once(reader)
        reason = await buffer.read(length)

        if not self.server_has_initiated_close:
            if length > WebSocketWriter.MAX_LEN_7:
                code, reason = Reasons.PROTOCOL_ERROR.value, "control frame too long"
            else:
                code, reason = Reason.from_bytes(reason, length)
                if code == Reasons.NO_STATUS.value:
                    code = Reasons.NORMAL.value

            self.ensure_clean_close()
            await self.close(code, reason)

        self.state = State.CLOSING

        if self.read_task is not None:
            self.read_task.cancel()

    async def handle_undefined(self, reader, fin):
        logger.debug(f"Received invalid opcode from client {self.addr, self.port}.")

        await self.close_with_read(reader, Reasons.PROTOCOL_ERROR.value, "invalid opcode")


HANDLERS = {opcode: Client.handle_undefined for opcode in range(0, 1 << 4)}
HANDLERS.update({
    DataType.CONTINUATION.value: Client.handle_continuation,
    DataType.TEXT.value: Client.handle_data(DataType.TEXT),
    DataType.BINARY.value: Client.handle_data(DataType.BINARY),
    DataType.CLOSE.value: Client.handle_close,
    DataType.PING.value: Client.handle_ping_or_pong(DataType.PING),
    DataType.PONG.value: Client.handle_ping_or_pong(DataType.PONG),
})
