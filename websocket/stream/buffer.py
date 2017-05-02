import asyncio

import logging

logger = logging.getLogger(__name__)


class Buffer:
    """ """
    def __init__(self, limit, loop):
        """Creates a new asynchronous buffer for reading and writing.
        
        :param limit: The maxsize if the buffer
        :type limit: int
        :param loop: The running event loop
        """
        self.backing = bytearray(limit)
        self._loop = loop
        self.read_available = 0
        self.write_available = limit
        self.limit = limit
        self.read_head = 0
        self.write_head = 0
        self.read_signal = asyncio.Event(loop=loop)
        self.write_signal = asyncio.Event(loop=loop)
        self.eof = False
        self.exc = None

    async def write(self, data):
        """Write some data to the buffer, length must not exceed the buffer limit, or else it will block forever.
        
        :param data: The data to write
        :type data: iterable of bytes
        """
        length = len(data)

        while self.write_available < length:
            await self.read_signal.wait()

        tail = self.limit - self.write_head
        if tail < length:
            self.backing[self.write_head:] = data[:tail]
            self.backing[:length - tail] = data[tail:]
            self.write_head = length - tail
        else:
            self.backing[self.write_head:self.write_head + length] = data
            self.write_head += length

        self.read_available += length
        self.write_available -= length

        self.write_signal.set()
        self.write_signal.clear()

    async def read(self, n=-1, chunksize=None):
        """Read data from the buffer. Reads until eof or n bytes.
        
        :param n: The amount of data to read.
        :return: A :class:`bytearray` with the data
        """
        if chunksize is None:
            chunksize = self.limit//8

        if n < 0:
            buffer = bytearray(chunksize)
            result = bytearray()
            while not self.eof:
                read = await self.read_into(buffer, chunksize)
                result.extend(buffer[:read])

            return result
        else:
            read = 0
            result = bytearray(n)
            while n - read > chunksize:
                read += await self.read_into(result, chunksize, offset=read)

            if n > 0:
                read += await self.read_into(result, n, offset=read)

        return result

    async def read_into_exactly(self, buffer, n):
        """Read data from the buffer into a bytearray. Reads n bytes or throws an exception if reading eof.

        :param buffer: The bytearray to write the data into.
        :param n: The amount of data to read.
        """
        while self.read_available < n and not self.eof and not self.exc:
            await self.write_signal.wait()

        if self.exc:
            raise self.exc

        if self.eof:
            if self.read_available < n:
                raise IncompleteReadError(f"{self.read_available} bytes available of {n} expected bytes")

        if n == 0:
            return n

        tail = self.read_head + n
        if tail > self.limit:
            remaining = self.limit - self.read_head
            buffer[:remaining] = self.backing[self.read_head:self.limit]
            buffer[remaining:n] = self.backing[:n - remaining]
            self.read_head = n - remaining
        else:
            buffer[:n] = self.backing[self.read_head:tail]
            self.read_head = tail

        self.read_available -= n
        self.write_available += n

        self.read_signal.set()
        self.read_signal.clear()

    async def read_into(self, buffer, n, offset=0):
        """Read data from the buffer into a bytearray. Reads until eof or n bytes.

        :param buffer: The bytearray to write the data into.
        :param n: The amount of data to read.
        :param offset: The index into buffer to write to.
        """
        while self.read_available < n and not self.eof and not self.exc:
            await self.write_signal.wait()

        if self.exc:
            raise self.exc

        if self.eof:
            n = min(self.read_available, n)

        if n == 0:
            return n

        tail = self.read_head + n
        if tail > self.limit:
            remaining = self.limit - self.read_head
            buffer[offset:offset + remaining] = self.backing[self.read_head:self.limit]
            buffer[offset + remaining:n] = self.backing[:n - remaining]
            self.read_head = n - remaining
        else:
            buffer[offset:offset + n] = self.backing[self.read_head:tail]
            self.read_head = tail

        self.read_available -= n
        self.write_available += n

        self.read_signal.set()
        self.read_signal.clear()
        return n

    def feed_eof(self):
        """Feed the buffer with `end of file`"""
        self.eof = True
        self.write_available = 0
        self.write_signal.set()

    def empty(self):
        """
        :return: True iff there is no more data to read.
        """
        return self.read_available == 0

    def at_eof(self):
        """
        :return: True iff there is no more data to read AND we have been fed `end of file`.
        """
        return self.eof and self.read_available == 0

    def set_exception(self, exc):
        """Set an exception to raise at next read."""
        self.exc = exc
        self.write_available = 0
        self.write_signal.set()


class IncompleteReadError(Exception):
    pass
