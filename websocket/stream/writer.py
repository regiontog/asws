"""
You should not make an instance of the WebSocketWriter class yourself, rather you should only 
make use of it through :attr:`websocket.client.Client.writer`

>>> client.writer.send('Hello World!')
"""
import asyncio
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

    HEADER_FIN_SET = 1 << 7

    def __init__(self, writer, loop):
        self.loop = loop
        self.writer = writer
        self.closed = False
        self.write_lock = asyncio.Lock(loop=loop)

    def ensure_open(self, force):
        if self.closed and not force:
            logger.warning("You are trying to send data to the client, but the server has initiated close with "
                           "client, use the force keyword if you still want to send messages.")
            return False

        return True

    async def send(self, data, force=False):
        """Send some data to the client, the type of data is determined from the data parameter.
        
        :param data: The data you wish to send, must be either :class:`str` or :class:`bytes`. 
        :param force: If true send message even if the connection is closing e.g. we got valid message after having previously been sent a close frame from the client or after having received invalid frame(s) 
        :type force: bool
        """
        with (await self.write_lock):
            if not self.ensure_open(force):
                return

            if isinstance(data, str):
                kind = DataType.TEXT
            else:
                kind = DataType.BINARY

            logger.debug(f"Sending {kind.name.lower()} to client.")
            self.write_frame((kind.value | WebSocketWriter.HEADER_FIN_SET).to_bytes(1, 'big'), data, len(data))
            await self.writer.drain()

    async def close(self, close_code, reason):
        with (await self.write_lock):
            logger.debug("Sending close to client.")

            if close_code == Reasons.NO_STATUS.value:
                self.write_frame(b'\x88', [], 0)
                await self.writer.drain()
            else:
                data = reason.encode()
                length = 2 + len(data)

                if length > WebSocketWriter.MAX_LEN_7:
                    raise Exception(f"Control frames(close) may not be over {WebSocketWriter.MAX_LEN_7} bytes.")

                self.write_frame(b'\x88', b''.join([close_code.code, data]), length)
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

        self.write_frame(b'\x89', payload, length)
        await self.writer.drain()

    async def pong(self, length, payload):
        """Send a pong to the client.

        :param payload: The payload to send with the ping.
        :type payload: bytes
        :param length: The length of the payload.
        :type length: int
        """
        logger.debug("Sending pong to client.")
        self.write_frame(b'\x8A', payload, length)
        await self.writer.drain()

    def write_frame(self, header, data, length):
        """Low level method to write a frame to the client, does not flush.
        
        :param header: The frame header, containing the frame type and the fin bit 
        :param data:  The data to include in the frame
        :param length:  The length of the data
        """
        frame = bytearray(header)

        if length > WebSocketWriter.MAX_LEN_64:
            raise Exception("Message too big, fragment it.")
        elif length > WebSocketWriter.MAX_LEN_16:
            frame.extend(WebSocketWriter.LENGTH_OVER_16)
            frame.extend(length.to_bytes(8, 'big'))
        elif length > WebSocketWriter.MAX_LEN_7:
            frame.extend(WebSocketWriter.LENGTH_OVER_7)
            frame.extend(length.to_bytes(2, 'big'))
        else:
            frame.extend(length.to_bytes(1, 'big'))

        frame.extend(data)
        self.writer.write(frame)

    def fragment(self):
        """Create a async context manager that can send fragmented messages.
        
        :return: :class:`~websocket.stream.fragment.FragmentContext`
        """
        return FragmentContext(self, self.loop)

    async def feed(self, buffer, op_code=None, chunksize=1024, drain_every=4096, force=False):
        """Feed the contents of a :class:`~websocket.stream.buffer.Buffer` to the client in `chunksize` fragments.
        
        :param buffer: The buffer to read from
        :type buffer: Buffer
        :param op_code: The type of data to send, see :class:`~websocket.enums.DataType`, if None try to read buffer.data_type as if buffer was a :class:`~websocket.stream.reader.WebSocketReader`
        :type op_code: int
        :param chunksize: The size of each fragment
        :type chunksize: int
        :param drain_every: How often we forcefully drain the writer
        :type drain_every: int
        :param force: If true send message even if the connection is closing e.g. we got valid message after having previously been sent a close frame from the client or after having received invalid frame(s) 
        :type force: bool
        """
        data = bytearray(chunksize)

        if op_code is None:
            op_code = buffer.data_type.value

        with (await self.write_lock):
            if not self.ensure_open(force):
                return

            written_since_drain = 0
            length = await buffer.read_into(data, chunksize)
            fin = buffer.at_eof()

            self.write_frame((op_code | fin << 7).to_bytes(1, 'big'), data[:length], length)
            written_since_drain += length

            while not fin:
                length = await buffer.read_into(data, chunksize)
                fin = buffer.at_eof()

                self.write_frame((fin << 7).to_bytes(1, 'big'), data[:length], length)
                written_since_drain += length
                if written_since_drain > drain_every:
                    await self.writer.drain()
                    written_since_drain = 0

            await self.writer.drain()
