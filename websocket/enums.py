from enum import Enum, auto


class State(Enum):
    """Enum containing the different states an connection may be in."""
    CONNECTING = auto()
    """The connection is in the connecting state, this is before the handshake is complete."""
    OPEN = auto()
    """The connection has completed handshake successfully."""
    CLOSING = auto()
    """The connection is going down."""


class DataType(Enum):
    """Enum of all frame operation codes"""
    NONE = -1
    """No data type"""
    CONTINUATION = 0x0
    """Continuation frame"""
    TEXT = 0x1
    """Text data frame"""
    BINARY = 0x2
    """Binary data frame"""
    CLOSE = 0x8
    """Close control frame"""
    PING = 0x9
    """Ping control frame"""
    PONG = 0xA
    """Pong control frame"""

    def header(self, flags):
        return (self.value | flags << 4).to_bytes(1, 'big')
