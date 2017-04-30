import logging

from .fragment import FragmentContext
from ..enums import DataType
from ..reasons import Reasons

logger = logging.getLogger(__name__)


class WebSocketWriter:
    MAX_LEN_7 = (1 << 7) - 3  # We must subtract 2 more here to make room for the special length codes 126 and 127
    MAX_LEN_16 = (1 << 16) - 1
    MAX_LEN_64 = (1 << 64) - 1

    LENGTH_OVER_7 = 126
    LENGTH_OVER_16 = 127
    LENGTH_OVER_7 = LENGTH_OVER_7.to_bytes(1, 'big')
    LENGTH_OVER_16 = LENGTH_OVER_16.to_bytes(1, 'big')

    def __init__(self, writer, loop):
        self.loop = loop
        self.writer = writer
        self.closed = False

    def ensure_open(self, force):
        if self.closed and not force:
            logger.warning("You are trying to send data to the client, but the server has initiated close with "
                           "client, use the force keyword if you still want to send messages.")
            return False

        return True

    async def send(self, data, kind=None, force=False):
        if not self.ensure_open(force):
            return

        if kind is None:
            if isinstance(data, str):
                kind = DataType.TEXT
            else:
                kind = DataType.BINARY

        logger.debug(f"Sending {kind.name.lower()} to client.")
        self.writer.write(kind.header(8))
        await self.raw_send(data, kind)

    async def raw_send(self, data, kind):
        if kind == DataType.TEXT:
            data = data.encode()

        length = len(data)

        if length > WebSocketWriter.MAX_LEN_64:
            raise Exception("Message too big, fragment it.")  # TODO: Auto fragment it
        elif length > WebSocketWriter.MAX_LEN_16:
            self.writer.write(WebSocketWriter.LENGTH_OVER_16)
            self.writer.write(length.to_bytes(8, 'big'))
        elif length > WebSocketWriter.MAX_LEN_7:
            self.writer.write(WebSocketWriter.LENGTH_OVER_7)
            self.writer.write(length.to_bytes(2, 'big'))
        else:
            self.writer.write(length.to_bytes(1, 'big'))

        self.writer.write(data)
        await self.writer.drain()

    def fragment(self, kind=None):
        return FragmentContext(self, kind, self.loop)

    async def close(self, close_code, reason):
        logger.debug("Sending close to client.")

        if close_code == Reasons.NO_STATUS.value:
            length = 0

            self.writer.write(b'\x88')
            self.writer.write(length.to_bytes(1, 'big'))
            await self.writer.drain()
        else:
            data = reason.encode()
            length = 2 + len(data)

            if length > WebSocketWriter.MAX_LEN_7:
                raise Exception(f"Control frames(close) may not be over {WebSocketWriter.MAX_LEN_7} bytes.")

            self.writer.write(b'\x88')
            self.writer.write(length.to_bytes(1, 'big'))
            self.writer.write(close_code.code.to_bytes(2, 'big'))
            self.writer.write(data)
            await self.writer.drain()

        self.closed = True

    async def ping(self, data):
        logger.debug("Sending ping to client.")

        length = len(data)
        if length > WebSocketWriter.MAX_LEN_7:
            raise Exception(f"Control frames(ping) may not be over {WebSocketWriter.MAX_LEN_7} bytes.")

        self.writer.write(b'\x89')
        self.writer.write(length.to_bytes(1, 'big'))
        self.writer.write(data)
        await self.writer.drain()

    async def _pong(self, length, data):
        logger.debug("Sending pong to client.")
        self.writer.write(b'\x8A')
        self.writer.write(length.to_bytes(1, 'big'))
        self.writer.write(data)
        await self.writer.drain()
