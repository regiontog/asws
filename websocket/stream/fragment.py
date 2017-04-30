import asyncio
import logging

from ..enums import DataType

logger = logging.getLogger(__name__)


class FragmentContext:
    class Break(Exception):
        """Break out of the with statement"""

    def __init__(self, writer, kind, loop):
        self.loop = loop
        self.writer = writer
        self.data_type = kind
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

    async def send(self, fragment, force=False):
        if not self.writer.ensure_open(force):
            raise self.Break

        if self.data_type is None:
            if isinstance(fragment, str):
                self.data_type = DataType.TEXT
            else:
                self.data_type = DataType.BINARY

        if self.previous_fragment is not None:
            await self._push(self.previous_fragment)

        logger.debug("Queuing fragment")
        self.previous_fragment = fragment

    async def finish_send(self):
        if self.previous_fragment is not None:
            await self._push(self.previous_fragment, fin=True)
            await self.push_task

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type == self.Break:
            return True

        await self.finish_send()
