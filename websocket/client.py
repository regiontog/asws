import asyncio
import logging

from .enums import DataType, State
from .reasons import Reasons, Reason
from .stream.reader import WebSocketReader
from .stream.writer import WebSocketWriter

logger = logging.getLogger(__name__)


class Client:
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
            await self.writer._pong(length, payload)

        @self.pong
        async def on_pong(payload, length):
            pass

        @self.closed
        async def on_closed(reason):
            pass

    def message(self, fn):
        self.on_message = fn

    def ping(self, fn):
        self.on_ping = fn

    def pong(self, fn):
        self.on_pong = fn

    def closed(self, fn):
        self.on_closed = fn

    async def close_with_read(self, reader, code, reason):
        close = asyncio.ensure_future(self.close(code, reason), loop=self._loop)
        buffer = WebSocketReader(DataType.BINARY)
        length = await buffer.feed(reader)
        data = await buffer.readexactly(length)
        await close
        return data

    async def close(self, code, reason):
        if not self.server_has_initiated_close:
            self.server_has_initiated_close = True
            await self.writer.close(code, reason)

            # TODO: Kill in 5 secs if client dont respond

    async def _read_message(self, reader, fin):
        try:
            await self._reader.feed(reader)

            if fin:
                self.continuation = DataType.NONE
                self._reader.decoder.decode(b'', True)
                self._reader.feed_eof()
            else:
                self.continuation = self._reader.type
        except UnicodeDecodeError as e:
            self._reader.set_exception(e)
            await self.close(Reasons.INCONSISTENT_DATA.value,
                             f"{e.object[e.start:e.end]} at {e.start}-{e.end}: {e.reason}"[:WebSocketWriter.MAX_LEN_7])

    @staticmethod
    def handle_data(kind):
        async def handler(self, reader, fin):
            if self.continuation != DataType.NONE:
                self._reader.set_exception(Exception(
                    f"Received unexpected {kind.name.lower()} data frame from client {self.addr, self.port}, "
                    f"expected continuation."))

                await self.close_with_read(reader, Reasons.PROTOCOL_ERROR.value, "expected continuation frame")
                return

            logger.debug(f"Received {kind.name.lower()} data frame from client {self.addr, self.port}.")
            self.type = kind
            self._reader = WebSocketReader(kind)
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

    @staticmethod
    def handle_ping_or_pong(kind):
        async def handler(self, reader, fin):
            buffer = WebSocketReader(DataType.BINARY)
            feed = asyncio.ensure_future(buffer.feed(reader), loop=self._loop)

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
            data = await buffer.readexactly(length)
            if kind is DataType.PING:
                self._loop.create_task(self.on_ping(data, length))
            elif kind is DataType.PONG:
                self._loop.create_task(self.on_pong(data, length))

        return handler

    async def handle_close(self, reader, fin):
        logger.debug(f"Received close from client {self.addr, self.port}.")

        buffer = WebSocketReader(DataType.BINARY)
        length = await buffer.feed(reader)
        reason = await buffer.readexactly(length)

        asyncio.ensure_future(self.on_closed(reason), loop=self._loop)
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
