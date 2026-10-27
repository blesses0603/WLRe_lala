"""Independent verifier for the P0 golden cases.

This file deliberately imports NOTHING from ``wlre``. It is a second,
minimal implementation of the P0 wire/login/decode behavior, written only
from the cases and next/spec/behavior/*.md. If it agrees with the golden
files that were produced by the legacy implementation, the spec is
self-consistent and a port in another language can be checked the same way.

Run:  python3 -I next/spec/verify_golden.py
Exit code 0 = every case matched, 1 = at least one mismatch.
Only ``result`` and the event/packet fields are compared; ``error`` text is
informational and differs between languages (see spec/README.md).
"""
import json
import struct
import sys
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "golden"
MAGIC = b"\xc4\xc6"


class ProtoError(Exception):
    pass


# ---------------------------------------------------------------- primitives
class R:
    def __init__(self, data):
        self.d, self.o = bytes(data), 0

    @property
    def left(self):
        return len(self.d) - self.o

    def take(self, n):
        if n < 0 or n > self.left:
            raise ProtoError("short")
        v = self.d[self.o:self.o + n]
        self.o += n
        return v

    def f(self, fmt):
        return struct.unpack("<" + fmt, self.take(struct.calcsize("<" + fmt)))[0]

    def u8(self): return self.f("B")
    def u16(self): return self.f("H")
    def u32(self): return self.f("I")

    def ustr(self):
        n = self.u8()
        if n % 2:
            raise ProtoError("odd utf16")
        try:
            return self.take(n).decode("utf-16le").rstrip("\x00")
        except UnicodeDecodeError as exc:
            raise ProtoError("bad utf16") from exc

    def end(self):
        if self.left:
            raise ProtoError("trailing")


def encode_frame(main, sub, payload, key):
    body = bytes([main, sub]) + payload
    if len(body) > 65535:
        raise ProtoError("oversize")
    return bytes(b ^ key for b in MAGIC + struct.pack("<H", len(body)) + body)


class Stream:
    def __init__(self, key):
        self.k, self.buf = key, bytearray()

    def feed(self, data):
        self.buf.extend(b ^ self.k for b in data)
        out = []
        while len(self.buf) >= 4:
            if bytes(self.buf[:2]) != MAGIC:
                raise ProtoError("magic")
            size = struct.unpack_from("<H", self.buf, 2)[0]
            if size < 2:
                raise ProtoError("size")
            if len(self.buf) < size + 4:
                break
            body = bytes(self.buf[4:4 + size])
            out.append({"main": body[0], "sub": body[1], "payload_hex": body[2:].hex()})
            del self.buf[:4 + size]
        return out

    def finish(self):
        if self.buf:
            raise ProtoError("leftover")


# ---------------------------------------------------------------- login
def login_packet(account, password, kind, platform, language):
    try:
        a, p = account.encode("ascii"), password.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ProtoError("non-ascii") from exc
    if not a or not p:
        raise ProtoError("empty")
    payload = bytes([kind, 0, platform, language, len(a)]) + a + bytes([len(p)]) + p
    return {"main": 63, "sub": 7, "payload_hex": payload.hex()}


def select_packet(index):
    if index not in (1, 2):
        raise ProtoError("index")
    return {"main": 63, "sub": 2, "payload_hex": bytes([index]).hex()}


# ---------------------------------------------------------------- decode (P0 subset)
def role_list(r):
    out = []
    while r.left:
        d = {"index": r.u8(), "name": r.ustr(), "level": r.u8(), "element": r.u8(),
             "max_hp": r.u32(), "hp": r.u32(), "max_sp": r.u32(), "sp": r.u32(),
             "exp": r.f("q"), "gold": r.u32(), "sex": r.u8(), "head": r.u8(),
             "palette1": r.u32(), "palette5": r.u32(), "degree": r.u8(), "job": r.u8(),
             "scene": r.u16(), "delete_time": r.f("d"), "locked": bool(r.u8())}
        if d["index"] not in (1, 2):
            raise ProtoError("role index")
        b = {"core_hp": r.u32(), "core_sp": r.u32(), "emblem_hp": r.u32(), "emblem_sp": r.u32(),
             "ride_hp": r.u16(), "star_hp": r.f("i"), "star_sp": r.f("i"),
             "relation_hp": r.u32(), "relation_sp": r.u32()}
        d["bonuses"] = b
        d["max_hp"] += sum(v for k, v in b.items() if k.endswith("_hp"))
        d["max_sp"] += sum(v for k, v in b.items() if k.endswith("_sp"))
        out.append(d)
    return out


def world_player(r):
    d = {"role_id": r.u32(), "sex": r.u8(), "scene": r.u16(), "x": r.u16(), "y": r.u16(),
         "face": r.u8(), "head": r.u8(), "body": r.u8(), "palette1": r.u32(), "palette5": r.u32(),
         "header_frame": r.u8(), "second_job_effect": bool(r.u8())}
    d["equips"] = [{"item_id": r.u16(), "design_id": r.u32()} for _ in range(r.u8())]
    d["name"] = r.ustr()
    r.take(8)
    r.ustr()
    d["title_id"] = r.u16()
    return d


def decode(main, sub, payload):
    r = R(payload)
    ev = {"main": main, "sub": sub}
    key = (main, sub)
    if key == (63, 7):
        ev.update(type="login_result", result=r.u8(), login_kind=r.u8())
    elif key == (1, 23):
        ev.update(type="heartbeat_request")
    elif key == (1, 11):
        ev.update(type="initial_data_complete")
    elif key == (1, 4):
        ev.update(type="account_identity", account_id=r.u32())
        for _ in range(3):
            r.take(r.u8())
    elif key == (63, 1):
        ev.update(type="role_list_available", roles=role_list(r), parsed=True)
    elif key == (3, 1):
        ev.update(type="world_player", player=world_player(r))
    elif key in ((26, 1), (26, 2)):
        amount, flag = r.u32(), r.u8()
        if flag not in (0, 1):
            raise ProtoError("flag")
        ev.update(type="gold_delta", delta=amount if sub == 1 else -amount, notify=bool(flag))
    elif key == (26, 4):
        ev.update(type="gold_snapshot", amount=r.u32())
    elif key == (51, 1):
        if r.left % 7:
            return dict(ev, type="battle_attribute_invalid", payload_bytes=r.left,
                        complete_records=r.left // 7, trailing_bytes=r.left % 7)
        vals = []
        while r.left:
            vals.append({"col": r.u8(), "row": r.u8(), "kind": r.u8(), "value": r.u32()})
        ev.update(type="battle_attribute_set", values=vals)
    else:
        return dict(ev, type="unimplemented", payload_bytes=len(payload))
    r.end()
    return ev


# ---------------------------------------------------------------- session model (independent)
class SessionError(Exception):
    def __init__(self, kind):
        super().__init__(kind)
        self.kind = kind


class Session:
    """Second implementation of the P0 session reactions, written from the behavior doc."""

    def __init__(self, role_index):
        self.role_index = role_index
        self.authenticated = False
        self.world_ack = False
        self.phase = "connecting"
        self.init_done = False
        self.has_player = False

    def snapshot(self):
        return {"authenticated": self.authenticated, "world_acknowledged": self.world_ack,
                "phase": self.phase, "initial_data_complete": self.init_done, "has_player": self.has_player}

    def receive(self, main, sub, payload):
        ev = decode(main, sub, payload)              # may raise ProtoError (not expected in scenarios)
        t = ev["type"]
        # state layer first (State.apply), then the session layer (SessionLogic.receive)
        if t == "login_result":
            self.phase = "authenticated" if ev["result"] == 0 else "login_failed"
        elif t == "role_list_available":
            self.phase = "role_selection"
        elif t == "world_player":
            self.has_player, self.phase = True, "world_received"
        elif t == "initial_data_complete":
            self.init_done = True
        sent = []
        if t == "heartbeat_request":
            sent.append({"main": 63, "sub": 5, "payload_hex": ""})
        elif t == "login_result":
            if ev["result"] != 0:
                raise SessionError("login_rejected")
            if ev["login_kind"] != 2:
                raise SessionError("protocol_error")
            self.authenticated = True
        elif t == "role_list_available" and self.role_index is not None:
            sent.append(select_packet(self.role_index))
            self.phase = "role_selected_awaiting_world"
        if self.has_player and self.init_done and not self.world_ack:
            sent += [{"main": 12, "sub": 1, "payload_hex": ""}, {"main": 3, "sub": 2, "payload_hex": ""}]
            self.world_ack, self.phase = True, "world_ready"
        return sent


def check_scenario(case):
    sess = Session(case["role_index"])
    for i, step in enumerate(case["steps"]):
        want = step["expect"]
        if step.get("new_session"):
            sess = Session(case["role_index"])
            got = {"state": sess.snapshot()}
        else:
            p = step["receive"]
            try:
                sent = sess.receive(p["main"], p["sub"], bytes.fromhex(p["payload_hex"]))
                got = {"sent": sent, "error": None, "state": sess.snapshot()}
            except SessionError as exc:
                got = {"sent": [], "error": exc.kind, "state": sess.snapshot()}
        if got != want:
            return f"step {i}: expected {want!r}\n      got      {got!r}"
    return None


# ---------------------------------------------------------------- runner
def check(case):
    t, exp = case["type"], case["expected"] if "expected" in case else None
    if t == "scenario":
        return check_scenario(case)
    try:
        if t == "wire_encode":
            p = case["packet"]
            got = {"result": "ok", "frame_hex": encode_frame(p["main"], p["sub"], bytes.fromhex(p["payload_hex"]), case["key"]).hex()}
        elif t == "wire_encode_oversize":
            try:
                encode_frame(1, 1, bytes(case["payload_length"]), case["key"])
                got = {"result": "ok"}
            except ProtoError:
                got = {"result": "rejected"}
        elif t == "wire_stream":
            s, pk = Stream(case["key"]), []
            try:
                for c in case["chunks_hex"]:
                    pk += s.feed(bytes.fromhex(c))
                got = {"result": "ok", "packets": pk}
            except ProtoError:
                got = {"result": "rejected", "packets": pk}
            if got["result"] == "ok" and case.get("call_finish"):
                try:
                    s.finish()
                    got["finish_result"] = "ok"
                except ProtoError:
                    got["finish_result"] = "rejected"
        elif t == "encode":
            a = case["args"]
            if case["command"] == "login":
                pkt = login_packet(a["account"], a["password"], a["login_kind"], a["platform"], a["language"])
            else:
                pkt = select_packet(a["index"])
            got = {"result": "ok", "packet": pkt}
            if "frame_hex" in exp:
                got["frame_hex"] = encode_frame(pkt["main"], pkt["sub"], bytes.fromhex(pkt["payload_hex"]), 0xAD).hex()
        elif t == "decode":
            p = case["packet"]
            got = {"result": "ok", "event": decode(p["main"], p["sub"], bytes.fromhex(p["payload_hex"]))}
        else:
            return f"unknown case type {t}"
    except ProtoError:
        got = {"result": "rejected"}
    want = {k: v for k, v in exp.items() if k not in ("error", "finish_error")}
    if t == "wire_stream" and want.get("result") == "rejected":
        got["packets"] = got.get("packets", [])
    got = {k: v for k, v in got.items() if k in want or k == "result"}
    return None if got == want else f"expected {want!r}\n      got      {got!r}"


def main():
    files = sorted(GOLDEN.rglob("*.json"))
    bad = 0
    for f in files:
        case = json.loads(f.read_text(encoding="utf-8"))
        err = check(case)
        if err:
            bad += 1
            print(f"FAIL {case['id']}\n      {err}")
    print(f"{len(files) - bad}/{len(files)} golden cases matched")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
