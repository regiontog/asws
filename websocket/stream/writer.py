"""
You should not make an instance of the WebSocketWriter class yourself, rather you should only 
make use of it through :attr:`websocket.client.Client.writer`

>>> client.writer.send('Hello World!')
"""
import logging

from .fragment import FragmentContext
from ..enums import DataType
from ..reasons import Reasons

logger = logging.getLogger(__name__)


class WebSocketWriter:
    """
    :ivar closed: True iff the server has sent a close frame to the client.
    """
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

    async def send(self, data, force=False):
        """Send a data frame to the client, the type of data is determined from the data parameter.
        
        :param data: The data you with to send, must be either :class:`str` or :class:`bytes`. 
        :param force: If true send message even if the connection is closing e.g. we got valid message after having previously been sent a close frame from the client or after having received invalid frame(s) 
        :type force: bool
        """
        if not self.ensure_open(force):
            return

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

    def fragment(self, chunksize=512):
        """Create a async context manager that can send fragmented messages.
        
        :param chunksize: The size of each fragment to send.
        :type chunksize: int
        
        :return: :class:`~websocket.stream.fragment.FragmentContext`
        """
        return FragmentContext(self, self.loop)

    async def close(self, close_code, reason):
        logger.debug("Sending close to client.")

        if close_code == Reasons.NO_STATUS.value:
            self.writer.write(b'\x88')
            self.writer.write((0).to_bytes(1, 'big'))
            await self.writer.drain()
        else:
            data = reason.encode()
            length = 2 + len(data)

            if length > WebSocketWriter.MAX_LEN_7:
                raise Exception(f"Control frames(close) may not be over {WebSocketWriter.MAX_LEN_7} bytes.")

            self.writer.write(b'\x88')
            self.writer.write(length.to_bytes(1, 'big'))
            self.writer.write(close_code.code)
            self.writer.write(data)
            await self.writer.drain()

        self.closed = True

    async def ping(self, payload=b''):
        """Send a ping to the client.
        
        :param payload: The payload to send with the ping.
        :type payload: bytes
        """
        logger.debug("Sending ping to client.")

        length = len(payload)
        if length > WebSocketWriter.MAX_LEN_7:
            raise Exception(f"Control frames(ping) may not be over {WebSocketWriter.MAX_LEN_7} bytes.")

        self.writer.write(b'\x89')
        self.writer.write(length.to_bytes(1, 'big'))
        self.writer.write(payload)
        await self.writer.drain()

    async def pong(self, length, payload):
        """Send a pong to the client.

        :param payload: The payload to send with the ping.
        :type payload: bytes
        :param length: The length of the payload.
        :type length: int
        """
        logger.debug("Sending pong to client.")
        self.writer.write(b'\x8A')
        self.writer.write(length.to_bytes(1, 'big'))
        self.writer.write(payload)
        await self.writer.drain()
