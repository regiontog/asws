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

from ..enums import DataType

logger = logging.getLogger(__name__)


class WebSocketReader(asyncio.StreamReader):
    """
    :ivar data_type: The type of data frame the client sent us, this is the default kind for :meth:`get`.
    :type data_type: :class:`~websocket.enums.DataType`
    """
    BUFFER_SIZE = 128
    MASK_BIT = 1 << 7
    FIN_BIT = 1 << 7
    RSV_BITS = 0b111 << 4
    OP_CODE_BITS = 0b1111

    decoder_factory = codecs.getincrementaldecoder('utf8')

    def __init__(self, kind):
        super().__init__()
        self.data_type = kind
        self.decoder = WebSocketReader.decoder_factory()

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

    async def feed(self, reader):
        mask_flag, length = await WebSocketReader._parse_length_and_mask_flag(reader)
        return await self._feed(reader, length, mask_flag)

    async def _feed(self, reader, length, mask_flag):
        if self.data_type is DataType.TEXT:
            async for data in self._parse_raw(reader, mask_flag, length):
                self.decoder.decode(data)
                self.feed_data(data)
        else:
            async for data in self._parse_raw(reader, mask_flag, length):
                self.feed_data(data)

        return length

    @staticmethod
    async def _parse_length_and_mask_flag(reader):
        data = await reader.readexactly(1)
        return (data[0] & WebSocketReader.MASK_BIT) != 0, data[0] & ~WebSocketReader.MASK_BIT

    async def _parse_raw(self, reader, mask_flag, length):
        # "The form '!' is available for those poor souls who claim they can’t remember whether network byte order is
        # big-endian or little-endian."
        # - <https://docs.python.org/3/library/struct.html>

        if length == 126:
            data = await reader.readexactly(2)
            length, = struct.unpack('!H', data)
        elif length == 127:
            data = await reader.readexactly(8)
            length, = struct.unpack('!Q', data)

        if not mask_flag:
            # TODO: Reject frame per <https://tools.ietf.org/html/rfc6455#section-5.1>
            logger.warning("Received message from client without mask.")

            while length > WebSocketReader.BUFFER_SIZE:
                yield await reader.readexactly(WebSocketReader.BUFFER_SIZE)
                length -= WebSocketReader.BUFFER_SIZE

            yield await reader.readexactly(length)
        else:
            mask = await reader.readexactly(4)
            buffer = bytearray(WebSocketReader.BUFFER_SIZE)

            to_read = min(WebSocketReader.BUFFER_SIZE, length)
            buffer[:] = await reader.readexactly(to_read)
            length -= to_read
            task = asyncio.ensure_future(WebSocketReader._unmask(mask, buffer[:], to_read), loop=self._loop)

            while length > WebSocketReader.BUFFER_SIZE:
                buffer[:] = await reader.readexactly(WebSocketReader.BUFFER_SIZE)
                length -= WebSocketReader.BUFFER_SIZE
                yield await task

                task = asyncio.ensure_future(WebSocketReader._unmask(mask, buffer[:], WebSocketReader.BUFFER_SIZE),
                                             loop=self._loop)

            if length > 0:
                buffer[:] = await reader.readexactly(length)
                yield await task
                await WebSocketReader._unmask(mask, buffer, length)
                yield buffer[:length]
            else:
                yield await task

    @staticmethod
    async def _unmask(mask, buffer, num, sleep_opt=4):
        # sleep_at = num/sleep_opt
        for i in range(num):
            buffer[i] ^= mask[i % 4]

            # if i % sleep_at == 0:
            #     # Allow other corutines to do work, should benchmark to see if this actually helps.
            #     await asyncio.sleep(0, loop=self._loop)

        return buffer
