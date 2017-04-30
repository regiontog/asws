"""
You should not make an instance of the FragmentContext class yourself, rather you should only 
get instances through :meth:`websocket.stream.writer.WebSocketWriter.fragment`

>>> async with client.writer.fragment() as stream:
...     stream.send('Hello ')
...     stream.send("World!")
"""
import asyncio
import logging

from ..enums import DataType

logger = logging.getLogger(__name__)


class FragmentContext:
    """A context manager that can send fragments to a client."""
    class Break(Exception):
        pass

    def __init__(self, writer, loop):
        self.loop = loop
        self.writer = writer
        self.data_type = None
        self.previous_fragment = None  # We need to track this so that we can set the fin bit on the last fragment.
        self.push_task = None
        self.first_write = True

    async def _push(self, fragment, fin=False):
        if self.push_task is not None and not self.push_task.done():
            await self.push_task

        self.push_task = asyncio.ensure_future(self.write(fragment, fin), loop=self.loop)

    async def write(self, fragment, fin):
        op_code = 0
        if self.first_write:
            logger.debug(f"Start fragment write: fin = {fin}")
            op_code = self.data_type.value
            self.first_write = False
        else:
            logger.debug(f"Fragment continuation write: fin = {fin}")

        self.writer.writer.write((op_code | fin << 7).to_bytes(1, 'big'))
        await self.writer.raw_send(fragment, self.data_type)

    async def send(self, data, force=False):
        """Que a message to be sent, it will be chopped into fragments and accumulated with other fragments
        
        :param data: The data you with to send, must be either :class:`str` or :class:`bytes`. 
        :param force: If true send message even if the connection is closing e.g. we got valid message after having previously been sent a close frame from the client or after having received invalid frame(s) 
        :type force: bool
        """
        if not self.writer.ensure_open(force):
            raise self.Break

        if self.data_type is None:
            if isinstance(data, str):
                self.data_type = DataType.TEXT
            else:
                self.data_type = DataType.BINARY

        if self.previous_fragment is not None:
            await self._push(self.previous_fragment)

        logger.debug("Queuing fragment")
        self.previous_fragment = data

    async def finish_send(self):
        if self.previous_fragment is not None:
            await self._push(self.previous_fragment, fin=True)
            await self.push_task

    async def __aenter__(self):
        """Enter the context manager"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the context manager"""
        if exc_type == self.Break:
            return True

        await self.finish_send()
