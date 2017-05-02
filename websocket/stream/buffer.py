import asyncio


class Buffer:
    def __init__(self, limit, loop):
        self.backing = bytearray(limit)
        self.read_available = 0
        self.write_available = limit
        self.limit = limit
        self.read_head = 0
        self.write_head = 0
        self.read_signal = asyncio.Event(loop=loop)
        self.write_signal = asyncio.Event(loop=loop)
        self.eof = False

    async def write(self, data):
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

    async def read(self, n):
        buffer = bytearray(n)
        read = await self.read_into(buffer, n)
        return buffer[:read]

    async def read_into(self, buffer, n, offset=0):
        while self.read_available < n and not self.eof:
            await self.write_signal.wait()

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
        self.eof = True
        self.write_available = 0
        self.write_signal.set()

    def empty(self):
        return self.read_available == 0

    def at_eof(self):
        return self.eof and self.read_available == 0
