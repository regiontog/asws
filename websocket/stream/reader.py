"""
You should not make an instance of the WebSocketReader class yourself, rather you should only make use of it through a 
callback registerd with :meth:`~websocket.client.Client.message`

>>> @client.message
>>> async def on_message(reader: WebSocketReader):
...     # Read from the reader here...
...     print(await reader.get())
"""

import asyncio
import codecs
import logging
import struct

from websocket.reasons import Reasons
from websocket.stream.writer import WebSocketWriter
from ..enums import DataType

logger = logging.getLogger(__name__)


class WebSocketReader(asyncio.StreamReader):
    """
    :ivar data_type: The type of data frame the client sent us, this is the default kind for :meth:`get`.
    :type data_type: :class:`~websocket.enums.DataType`
    """
    BUFFER_SIZE = 1024
    QUE_MAXSIZE = 12
    MASK_BIT = 1 << 7
    FIN_BIT = 1 << 7
    RSV_BITS = 0b111 << 4
    OP_CODE_BITS = 0b1111

    decoder_factory = codecs.getincrementaldecoder('utf8')

    def __init__(self, kind, client, loop):
        super().__init__(loop=loop)
        self.data_type = kind
        self.client = client
        self.decoder = WebSocketReader.decoder_factory()

        self.que = asyncio.Queue(WebSocketReader.QUE_MAXSIZE)
        self.reading = True

        if self.data_type is DataType.TEXT:
            self.processor = asyncio.ensure_future(self.process_text(), loop=self._loop)
        else:
            self.processor = asyncio.ensure_future(self.process_binary(), loop=self._loop)

    async def get(self, kind=None):
        """Reads all of the bytes from the stream. 
         
        :param kind: Specifies the type of data returned, default is :attr:`~websocket.stream.reader.WebSocketReader.data_type`
        :type kind: :class:`~websocket.enums.DataType`
        
        :return: :class:`bytes` if kind is DataType.BINARY, :class:`str` if kind is DataType.TEXT
        """
        if kind is None:
            kind = self.data_type

        data = await self.read()
        if kind == DataType.TEXT:
            return data.decode()
        elif kind == DataType.BINARY:
            return data

    def done(self):
        asyncio.ensure_future(self.adone(), loop=self._loop)

    async def adone(self):
        self.reading = False

        try:
            if self.processor.done():
                exc = self.processor.exception()
                if exc:
                    raise exc

            if self.que.empty():
                self.processor.cancel()
                await self.processor
            else:
                await self.processor

            if self.data_type is DataType.TEXT:
                self.decoder.decode(b'', True)

            self.feed_eof()

        except UnicodeDecodeError as e:
            self.set_exception(e)
            await self.client.close(Reasons.INCONSISTENT_DATA.value,
                                    f"{e.object[e.start:e.end]} at {e.start}-{e.end}: {e.reason}"[:WebSocketWriter.MAX_LEN_7])

    async def process_text(self):
        try:
            while not self.que.empty() or self.reading:
                data, length, mask = await self.que.get()
                data = bytearray(data)
                for i in range(length):
                    data[i] ^= mask[i % 4]

                self.decoder.decode(data)
                self.feed_data(data)
        except UnicodeDecodeError as e:
            logger.debug("1")
            self.set_exception(e)
            raise
        except asyncio.CancelledError:
            pass

    async def process_binary(self):
        try:
            while not self.que.empty() or self.reading:
                data, length, mask = await self.que.get()
                data = bytearray(data)
                for i in range(length):
                    data[i] ^= mask[i % 4]

                self.feed_data(data)
        except asyncio.CancelledError:
            pass

    async def feed_once(self, reader):
        length = await self.feed(reader)
        self.done()
        return length

    async def feed(self, reader):
        data = await reader.readexactly(1)
        mask_flag = data[0] & WebSocketReader.MASK_BIT
        length = data[0] & ~WebSocketReader.MASK_BIT

        # "The form '!' is available for those poor souls who claim they can’t remember whether network byte order is
        # big-endian or little-endian."
        # - <https://docs.python.org/3/library/struct.html>
        if length == 126:
            data = await reader.readexactly(2)
            length, = struct.unpack('!H', data)
        elif length == 127:
            data = await reader.readexactly(8)
            length, = struct.unpack('!Q', data)

        left_to_read = length

        if not mask_flag:
            # TODO: Reject frame per <https://tools.ietf.org/html/rfc6455#section-5.1>
            logger.warning("Received message from client without mask.")
            await reader.readexactly(left_to_read)
            raise Exception("Received message from client without mask.")  # TODO: HANDLE

        mask = await reader.readexactly(4)

        first_read_size = min(WebSocketReader.BUFFER_SIZE, left_to_read)
        await self.que.put((await reader.readexactly(first_read_size), first_read_size, mask))
        left_to_read -= first_read_size

        while left_to_read > WebSocketReader.BUFFER_SIZE:
            await self.que.put(
                (await reader.readexactly(WebSocketReader.BUFFER_SIZE), WebSocketReader.BUFFER_SIZE, mask))
            left_to_read -= WebSocketReader.BUFFER_SIZE

        if left_to_read > 0:
            await self.que.put((await reader.readexactly(left_to_read), left_to_read, mask))

        return length
