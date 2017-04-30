import base64
import hashlib

newline = "\r\n"
sep = ": "
methods = ["GET"]
protocols = ["HTTP/1.1"]

supported_ws_versions = [13]


class BadRequestException(Exception):
    RESPONSE = b"HTTP/1.1 400 Bad Request\r\n"


class WebSocketConnection:
    MAGIC_STR = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, version, key):
        if version not in supported_ws_versions:
            raise BadRequestException(f"Unsupported websocket version {version}")

        self.version = version
        self.key = key

    def response(self):
        return b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + self.accept_key() + b"\r\n\r\n"

    def accept_key(self):
        m = hashlib.sha1()
        m.update(str.encode(self.key))
        m.update(WebSocketConnection.MAGIC_STR)
        return base64.b64encode(m.digest())


class Request:
    def __init__(self, request_line):
        self.attrs = {}

        request_line = request_line.split(" ")
        if request_line[0] not in methods:
            self.error(f"Unknown or invalid method {request_line[0]}.")

        self.method = request_line[0]
        self.protocol = request_line[2][:-2]  # Remove trailing \r\n

        if self.protocol not in protocols:
            self.error(f"Unknown protocol {self.protocol}.")

        self.path = request_line[1]

    def header(self, header):
        key, val = header.split(sep, 2)
        self.attrs[key] = val[:-2]  # Remove trailing \r\n

    def validate_header(self, header, value):
        return header in self.attrs and self.attrs[header].lower() == value

    def validate_websocket_request(self):
        if not self.validate_header("Connection", "upgrade"):
            self.error("Connection header must be of Upgrade type.")

        if not self.validate_header("Upgrade", "websocket"):
            self.error("Missing or invalid upgrade header.")

        if "Sec-WebSocket-Key" not in self.attrs:
            self.error("Missing Sec-WebSocket-Key header.")

        if "Sec-WebSocket-Version" not in self.attrs:
            self.error("Missing Sec-WebSocket-Version header.")

        self.websocket = WebSocketConnection(
            int(self.attrs["Sec-WebSocket-Version"]),
            self.attrs["Sec-WebSocket-Key"])

        return self.websocket.response()

    @staticmethod
    def error(msg):
        raise BadRequestException(msg)
