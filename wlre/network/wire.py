"""Strict packet primitives and the server codec observed in EXP_Monitor.

The outbound codec is a candidate until a real client capture validates it.
This module does not perform TCP sequence reassembly; see capture.py.
"""
import struct
from dataclasses import dataclass


class ProtocolError(ValueError):
    pass


class Reader:
    def __init__(self, data):
        self.data = bytes(data)
        self.offset = 0

    @property
    def remaining(self):
        return len(self.data) - self.offset

    def take(self, size):
        if size < 0 or size > self.remaining:
            raise ProtocolError(f"offset {self.offset}: need {size}, have {self.remaining}")
        result = self.data[self.offset:self.offset + size]
        self.offset += size
        return result

    def read(self, fmt):
        return struct.unpack("<" + fmt, self.take(struct.calcsize("<" + fmt)))[0]

    def u8(self): return self.read("B")
    def u16(self): return self.read("H")
    def u32(self): return self.read("I")
    def i32(self): return self.read("i")
    def i64(self): return self.read("q")

    def unicode8(self):
        size = self.u8()
        if size % 2:
            raise ProtocolError("odd UTF-16LE byte length")
        try:
            return self.take(size).decode("utf-16le").rstrip("\x00")
        except UnicodeDecodeError as exc:
            raise ProtocolError("invalid UTF-16LE string") from exc

    def end(self):
        if self.remaining:
            raise ProtocolError(f"unexpected trailing bytes: {self.remaining}")


class Writer:
    def __init__(self): self.data = bytearray()

    def write(self, fmt, value):
        try:
            self.data.extend(struct.pack("<" + fmt, value))
        except (struct.error, TypeError) as exc:
            raise ProtocolError(f"invalid {fmt} value") from exc
        return self

    def u8(self, v): return self.write("B", v)
    def u16(self, v): return self.write("H", v)
    def u32(self, v): return self.write("I", v)
    def raw(self, v):
        self.data.extend(v)
        return self
    def build(self): return bytes(self.data)


@dataclass(frozen=True)
class Packet:
    main: int
    sub: int
    payload: bytes = b""

    def body(self):
        return Writer().u8(self.main).u8(self.sub).raw(self.payload).build()

    @classmethod
    def from_body(cls, data):
        if len(data) < 2:
            raise ProtocolError("packet body has no main/sub header")
        return cls(data[0], data[1], bytes(data[2:]))


def encode(packet, xor_key=0xAD):
    body = packet.body()
    if len(body) > 65535:
        raise ProtocolError("body exceeds uint16 length")
    plain = b"\xc4\xc6" + struct.pack("<H", len(body)) + body
    return bytes(b ^ xor_key for b in plain)


class FrameDecoder:
    def __init__(self, xor_key=0xAD):
        if not 0 <= xor_key <= 255:
            raise ProtocolError("XOR key must be a byte")
        self.key = xor_key
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(b ^ self.key for b in data)
        packets = []
        while len(self.buffer) >= 4:
            if self.buffer[:2] != b"\xc4\xc6":
                raise ProtocolError("bad frame magic; incomplete capture or different wire codec")
            size = struct.unpack_from("<H", self.buffer, 2)[0]
            if size < 2:
                raise ProtocolError("frame shorter than main/sub header")
            if len(self.buffer) < size + 4:
                break
            packets.append(Packet.from_body(self.buffer[4:4 + size]))
            del self.buffer[:4 + size]
        return packets

    def finish(self):
        if self.buffer:
            raise ProtocolError(f"incomplete final frame: {len(self.buffer)} bytes")
