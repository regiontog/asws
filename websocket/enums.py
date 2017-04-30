from enum import Enum, auto


class State(Enum):
    CONNECTING = auto()
    OPEN = auto()
    CLOSING = auto()


class DataType(Enum):
    NONE = -1
    CONTINUATION = 0x0
    TEXT = 0x1
    BINARY = 0x2
    CLOSE = 0x8
    PING = 0x9
    PONG = 0xA

    def header(self, flags):
        return (self.value | flags << 4).to_bytes(1, 'big')
