import logging
import struct
from enum import Enum

logger = logging.getLogger(__name__)


class Reason:
    INSTANCES = {}

    def __init__(self, code, desc=''):
        if code in Reason.INSTANCES:
            raise Exception("Duplicate entry.")

        Reason.INSTANCES[code] = self
        self.code = code
        self.description = desc

    @classmethod
    def get(cls, code, desc=''):
        if code in Reason.INSTANCES:
            return Reason.INSTANCES[code]
        else:
            return Reason(code, desc)

    @staticmethod
    def from_bytes(data, length):
        if length == 0:
            return Reasons.NO_STATUS.value, ''
        elif length < 2:
            return Reasons.PROTOCOL_ERROR.value, 'invalid close code length'

        code, = struct.unpack('!H', data[:2])

        if code < Reasons.NORMAL.value.code or code in INVALID_CODES or code in UNDEFINED_CODES:
            logger.warning("Client sent invalid close code.")
            return Reasons.PROTOCOL_ERROR.value, 'invalid close code'

        try:
            reason = data[2:].decode()
            return Reason.get(code), reason
        except UnicodeDecodeError:
            return Reasons.PROTOCOL_ERROR.value, "invalid utf8 in close reason"


class Reasons(Enum):
    NORMAL = Reason(1000, "indicates a normal closure, meaning that the purpose for which the connection was "
                          "established has been fulfilled.")

    GOING_AWAY = Reason(1001, 'indicates that an endpoint is "going away", such as a server going down or a browser '
                              'having navigated away from a page.')

    PROTOCOL_ERROR = Reason(1002, 'indicates that an endpoint is terminating the connection due to a protocol error.')

    UNACCEPTABLE_DATA = Reason(1003,
                               'indicates that an endpoint is terminating the connection because it has received a '
                               'type of data it cannot accept (e.g., an endpoint that understands only text data MAY '
                               'send this if it receives a binary message).')

    RESERVED = Reason(1004, 'The specific meaning might be defined in the future.')

    NO_STATUS = Reason(1005,
                       'reserved value and MUST NOT be set as a status code in a Close control frame by an endpoint.  '
                       'It is designated for use in applications expecting a status code to indicate that no status '
                       'code was actually present.')

    ABNORMAL_CLOSE = Reason(1006,
                            'reserved value and MUST NOT be set as a status code in a Close control frame by an '
                            'endpoint. It is designated for use in applications expecting a status code to indicate '
                            'that the connection was closed abnormally, e.g., without sending or receiving a Close '
                            'control frame.')

    INCONSISTENT_DATA = Reason(1007,
                               'indicates that an endpoint is terminating the connection because it has received data '
                               'within a message that was not consistent with the type of the message (e.g., '
                               'non-UTF-8 [RFC3629] data within a text message).')

    POLICY_VIOLATION = Reason(1008,
                              'indicates that an endpoint is terminating the connection because it has received a '
                              'message that violates its policy.  This is a generic status code that can be returned '
                              'when there is no other more suitable status code (e.g., 1003 or 1009) or if there is a '
                              'need to hide specific details about the policy.')

    MESSAGE_TOO_BIG = Reason(1009,
                             'indicates that an endpoint is terminating the connection because it has received a '
                             'message that is too big for it to process.')

    EXTENSION_NOT_PRESENT = Reason(1010,
                                   "indicates that an endpoint (client) is terminating the connection because it has "
                                   "expected the server to negotiate one or more extension, but the server didn't "
                                   "return them in the response message of the WebSocket handshake.  The list of "
                                   "extensions that are needed SHOULD appear in the /reason/ part of the Close frame. "
                                   "Note that this status code is not used by the server, because it can fail the "
                                   "WebSocket handshake instead.")

    UNEXPECTED_CONDITION = Reason(1011,
                                  'indicates that a server is terminating the connection because it encountered an '
                                  'unexpected condition that prevented it from fulfilling the request.')

    TLS_HANDSHAKE_FAILURE = Reason(1015,
                                   "reserved value and MUST NOT be set as a status code in a Close control frame by an "
                                   "endpoint.  It is designated for use in applications expecting a status code to "
                                   "indicate that the connection was closed due to a failure to perform a TLS "
                                   "handshake (e.g., the server certificate can't be verified).")


INVALID_CODES = [reason.value.code for reason in [
    Reasons.RESERVED,
    Reasons.NO_STATUS,
    Reasons.ABNORMAL_CLOSE,
    Reasons.TLS_HANDSHAKE_FAILURE
]]

UNDEFINED_CODES = []
UNDEFINED_CODES.extend(range(1012, 1015))
UNDEFINED_CODES.extend(range(1016, 3000))
