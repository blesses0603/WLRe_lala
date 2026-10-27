"""Generate P0 golden packet cases from the legacy Python reference implementation.

Run from the repository root:  python3 -I next/tools-python/gen_golden.py

All account names, passwords, role names and numeric IDs below are synthetic
placeholders. Nothing here is a real capture. Every case records its source
grade so a Kotlin port can tell evidence apart (see next/spec/README.md).
The generator only imports the Tk-free protocol modules of ``wlre``.
"""
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wlre.network.wire import FrameDecoder, Packet, ProtocolError, encode  # noqa: E402
from wlre.network.protocol import decode, login, select_role  # noqa: E402

GOLDEN = ROOT / "next" / "spec" / "golden"
KEY = 0xAD
REF = {"grade": "reference_impl", "ref": "wlre/network/wire.py,protocol.py,layouts.py (read and executed)"}
SYN = {"grade": "synthetic", "ref": "hand-built boundary case"}


def hx(b):
    return bytes(b).hex()


def packet_json(p):
    return {"main": p.main, "sub": p.sub, "payload_hex": hx(p.payload)}


def write(group, case):
    path = GOLDEN / group / (case["id"].split("/")[-1] + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def u8str(text):
    raw = text.encode("utf-16le")
    return bytes([len(raw)]) + raw


# ---------------------------------------------------------------- wire
def wire_cases():
    p1 = Packet(1, 23)
    p2 = Packet(63, 2, b"\x01")
    p3 = Packet(26, 4, struct.pack("<I", 1234))
    f1, f2, f3 = encode(p1, KEY), encode(p2, KEY), encode(p3, KEY)

    for cid, pkt, frame in (("encode_empty_payload", p1, f1), ("encode_with_payload", p2, f2)):
        write("wire", {"id": f"wire/{cid}", "priority": "P0", "type": "wire_encode", "key": KEY,
                       "packet": packet_json(pkt), "expected": {"result": "ok", "frame_hex": hx(frame)},
                       "source": REF, "notes": "frame = XOR(key, C4 C6 + u16le(len(body)) + main + sub + payload)"})

    def stream(cid, chunks, finish=False, notes=""):
        dec = FrameDecoder(KEY)
        packets, error, finish_error = [], None, None
        try:
            for c in chunks:
                packets += [packet_json(p) for p in dec.feed(c)]
        except ProtocolError as exc:
            error = str(exc)
        if error is None and finish:
            try:
                dec.finish()
            except ProtocolError as exc:
                finish_error = str(exc)
        exp = {"result": "rejected" if error else "ok", "packets": packets}
        if error:
            exp["error"] = error
        if finish:
            exp["finish_result"] = "rejected" if finish_error else "ok"
            if finish_error:
                exp["finish_error"] = finish_error
        write("wire", {"id": f"wire/{cid}", "priority": "P0", "type": "wire_stream", "key": KEY,
                       "chunks_hex": [hx(c) for c in chunks], "call_finish": finish, "expected": exp,
                       "source": REF if not error else SYN, "notes": notes})

    stream("decode_single_frame", [f1])
    stream("decode_fragmented", [f2[:3], f2[3:5], f2[5:]], notes="frame split across 3 reads; no packet until complete")
    stream("decode_coalesced", [f1 + f2 + f3], notes="three frames in one read, order preserved")
    stream("decode_partial_then_rest", [f3 + f1[:2], f1[2:]], notes="complete frame followed by the head of the next")
    bad_magic = bytes(b ^ KEY for b in b"\x00\x00\x02\x00\x01\x17")
    stream("reject_bad_magic", [bad_magic], notes="magic != C4 C6 -> ProtocolError (whole stream is poisoned)")
    short = bytes(b ^ KEY for b in b"\xc4\xc6\x01\x00\x01")
    stream("reject_body_shorter_than_header", [short], notes="declared size < 2 cannot hold main/sub")
    stream("finish_with_incomplete_frame", [f2[:5]], finish=True, notes="finish() must report leftover bytes")
    stream("finish_clean", [f1 + f2], finish=True)

    over = {"id": "wire/reject_oversize_body", "priority": "P0", "type": "wire_encode_oversize", "key": KEY,
            "payload_length": 65534, "expected": {"result": "rejected"},
            "source": SYN, "notes": "body = 2 + payload_length = 65536 > uint16 -> encode must reject"}
    try:
        encode(Packet(1, 1, b"\x00" * 65534), KEY)
        over["expected"] = {"result": "ok"}
    except ProtocolError as exc:
        over["expected"]["error"] = str(exc)
    write("wire", over)

    ok_max = {"id": "wire/encode_max_body", "priority": "P0", "type": "wire_encode_oversize", "key": KEY,
              "payload_length": 65533, "expected": {"result": "ok"}, "source": SYN,
              "notes": "body = 65535 is the largest accepted size"}
    encode(Packet(1, 1, b"\x00" * 65533), KEY)
    write("wire", ok_max)


# ---------------------------------------------------------------- login / role select
def login_cases():
    for cid, args, notes in (
        ("encode_formal_login", ("testuser", "testpass", 2, 3, 0), "kind=2 formal login, platform=3, language=0"),
        ("encode_verify_login", ("testuser", "testpass", 0, 3, 0), "kind=0 account verification"),
    ):
        pkt = login(*args)
        write("login", {"id": f"login/{cid}", "priority": "P0", "type": "encode", "command": "login",
                        "args": {"account": args[0], "password": args[1], "login_kind": args[2],
                                 "platform": args[3], "language": args[4]},
                        "expected": {"result": "ok", "packet": packet_json(pkt),
                                     "frame_hex": hx(encode(pkt, KEY))},
                        "source": REF, "notes": notes + "; credentials are fake"})
    for cid, args, notes in (
        ("reject_empty_account", ("", "pw", 2, 3, 0), "empty credentials rejected before any byte is built"),
        ("reject_empty_password", ("user", "", 2, 3, 0), ""),
        ("reject_non_ascii", ("測試", "pw", 2, 3, 0), "non-ASCII encoding is explicitly unverified -> reject, never guess"),
    ):
        try:
            login(*args)
            raise SystemExit(f"{cid} unexpectedly accepted")
        except ProtocolError as exc:
            err = str(exc)
        write("login", {"id": f"login/{cid}", "priority": "P0", "type": "encode", "command": "login",
                        "args": {"account": args[0], "password": args[1], "login_kind": args[2],
                                 "platform": args[3], "language": args[4]},
                        "expected": {"result": "rejected", "error": err}, "source": REF, "notes": notes})
    for idx in (1, 2):
        pkt = select_role(idx)
        write("login", {"id": f"login/select_role_{idx}", "priority": "P0", "type": "encode",
                        "command": "select_role", "args": {"index": idx},
                        "expected": {"result": "ok", "packet": packet_json(pkt)}, "source": REF, "notes": ""})
    for idx in (0, 3):
        try:
            select_role(idx)
            raise SystemExit("select_role accepted bad index")
        except ProtocolError as exc:
            err = str(exc)
        write("login", {"id": f"login/reject_select_role_{idx}", "priority": "P0", "type": "encode",
                        "command": "select_role", "args": {"index": idx},
                        "expected": {"result": "rejected", "error": err}, "source": REF,
                        "notes": "only role slots 1 and 2 exist"})


# ---------------------------------------------------------------- decode
def dec_case(group, cid, pkt, notes="", source=REF, priority="P0"):
    try:
        ev = decode(pkt)
        exp = {"result": "ok", "event": ev}
    except ProtocolError as exc:
        exp = {"result": "rejected", "error": str(exc)}
    write(group, {"id": f"{group}/{cid}", "priority": priority, "type": "decode", "direction": "server_to_client",
                  "packet": packet_json(pkt), "expected": exp, "source": source, "notes": notes})


def role_payload(index, name, level=10):
    b = bytes([index]) + u8str(name) + bytes([level, 2])
    b += struct.pack("<IIII", 500, 480, 120, 100)          # max_hp hp max_sp sp
    b += struct.pack("<q", 123456)                          # exp
    b += struct.pack("<I", 777)                             # gold
    b += bytes([1, 3]) + struct.pack("<II", 11, 22)        # sex head palette1 palette5
    b += bytes([0, 5]) + struct.pack("<H", 11016)          # degree job scene
    b += struct.pack("<d", 0.0) + bytes([0])               # delete_time locked
    b += struct.pack("<IIIIH", 10, 20, 30, 40, 5)          # core_hp core_sp emblem_hp emblem_sp ride_hp
    b += struct.pack("<iiII", -1, 2, 3, 4)                 # star_hp star_sp relation_hp relation_sp
    return b


def world_player_payload():
    wp = struct.pack("<IBHHH", 9001, 1, 11016, 100, 200) + bytes([1, 2, 3]) + struct.pack("<II", 5, 6)
    wp += bytes([0, 0]) + bytes([2]) + struct.pack("<HI", 3001, 0) + struct.pack("<HI", 3002, 7)
    wp += u8str("Alice") + bytes(8) + u8str("") + struct.pack("<H", 12)
    return wp


def roles_payload():
    return role_payload(1, "測試甲", 10) + role_payload(2, "Beta", 55)


def decode_cases():
    dec_case("decode", "login_result_ok", Packet(63, 7, bytes([0, 2])), "result=0 kind=2")
    dec_case("decode", "login_result_rejected", Packet(63, 7, bytes([5, 2])), "non-zero result is still decoded; the session layer decides to raise")
    dec_case("decode", "heartbeat_request", Packet(1, 23), "session must answer with Packet(63,5) (see behavior doc)")
    dec_case("decode", "initial_data_complete", Packet(1, 11))
    acct = struct.pack("<I", 4242) + bytes([8]) + b"fakeuser" + bytes([8]) + b"fakepass" + bytes([1]) + b"1"
    dec_case("decode", "account_identity_drops_credentials", Packet(1, 4, acct),
             "server echoes account/password/save flag; decoder keeps ONLY account_id, never the strings", SYN)
    roles = roles_payload()
    dec_case("decode", "role_list_two_roles", Packet(63, 1, roles), "synthetic roles; name is u8 byte-length + UTF-16LE; "
             "max_hp/max_sp already include summed *_hp / *_sp bonuses", SYN)
    dec_case("decode", "role_list_truncated", Packet(63, 1, roles[:-3]), "truncation -> rejected, no partial list", SYN)
    bad = bytearray(role_payload(3, "Bad"))
    dec_case("decode", "role_list_invalid_index", Packet(63, 1, bytes(bad)), "index must be 1 or 2", SYN)
    dec_case("decode", "world_player", Packet(3, 1, world_player_payload()),
             "private namecard fields (8 bytes + signature) are consumed, not exposed", SYN)
    dec_case("decode", "gold_snapshot", Packet(26, 4, struct.pack("<I", 1234)))
    dec_case("decode", "gold_delta_gain_notify", Packet(26, 1, struct.pack("<IB", 50, 1)))
    dec_case("decode", "gold_delta_loss_silent", Packet(26, 2, struct.pack("<IB", 50, 0)), "sub 2 is a loss: delta is negative")
    dec_case("decode", "gold_delta_bad_flag", Packet(26, 1, struct.pack("<IB", 50, 7)), "flag must be 0 or 1", SYN)
    dec_case("decode", "gold_snapshot_trailing_bytes", Packet(26, 4, struct.pack("<I", 1) + b"\x00"),
             "strict decoding: trailing bytes are rejected", SYN)
    dec_case("decode", "unknown_packet_hides_payload", Packet(99, 99, b"secret-bytes"),
             "unknown packets report only payload_bytes, never the content (may hold credentials)", SYN)
    dec_case("decode", "battle_attribute_partial_record_dropped", Packet(51, 1, bytes(8)),
             "S51-1 uses 7-byte records; a partial record drops the WHOLE update and keeps state (tolerance case)", SYN, "P2")


# ---------------------------------------------------------------- session scenarios
def scenario_cases():
    """Drive the legacy SessionLogic exactly like run_client: decode -> State.apply -> logic.receive."""
    from wlre.core.state import State
    from wlre.network.client import SessionLogic

    sess = {}

    def new(role_index):
        sess["state"], sess["logic"] = State(phase="connecting"), SessionLogic(role_index)

    def snapshot():
        st, lg = sess["state"], sess["logic"]
        return {"authenticated": lg.authenticated, "world_acknowledged": lg.world_acknowledged,
                "phase": st.phase, "initial_data_complete": bool(st.initial_data_complete),
                "has_player": bool(st.player)}

    def classify(exc):
        return {"LoginRejected": "login_rejected", "ProtocolError": "protocol_error"}.get(type(exc).__name__, "other")

    def run(cid, role_index, script, notes, source=REF):
        new(role_index)
        steps = []
        for item in script:
            if item == "new_session":
                new(role_index)
                steps.append({"new_session": True, "expect": {"state": snapshot()}})
                continue
            pkt = item
            step = {"receive": packet_json(pkt)}
            try:
                ev = decode(pkt, sess["state"].player.get("role_id"))
                sess["state"].apply(ev)
                sent = sess["logic"].receive(ev, sess["state"])
                step["expect"] = {"sent": [packet_json(p) for p in sent], "error": None, "state": snapshot()}
            except Exception as exc:  # noqa: BLE001 - the error class is the observable behavior
                step["expect"] = {"sent": [], "error": classify(exc), "state": snapshot()}
            steps.append(step)
        write("scenario", {"id": f"scenario/{cid}", "priority": "P0", "type": "scenario", "role_index": role_index,
                           "steps": steps, "source": source, "notes": notes})

    ok = Packet(63, 7, bytes([0, 2]))
    roles = Packet(63, 1, roles_payload())
    player = Packet(3, 1, world_player_payload())
    done = Packet(1, 11)
    hb = Packet(1, 23)

    run("heartbeat_reply", None, [hb], "every S1-23 is answered with exactly one C63-5; state is untouched")
    run("login_ok_then_select_role", 1, [ok, roles],
        "after a formal login result and a role list, the configured role index is sent as C63-2")
    run("role_list_without_role_index", None, [ok, roles],
        "no configured role -> nothing is sent; phase waits at role_selection")
    run("login_rejected", 1, [Packet(63, 7, bytes([5, 2]))],
        "result != 0 ends the session; the state layer already recorded phase=login_failed")
    run("login_wrong_kind", 1, [Packet(63, 7, bytes([0, 0]))],
        "formal login must answer kind 2. OBSERVED QUIRK: State.apply already set phase=authenticated before the "
        "session layer raised; a port may choose to keep or tighten this", SYN)
    run("world_ready_complete_then_player", None, [done, player],
        "C12-1 and C3-2 are sent once both S1-11 and S3-1 have arrived, in this order")
    run("world_ready_player_then_complete", None, [player, done],
        "same acknowledgement when S3-1 arrives first")
    run("world_ack_sent_once", None, [player, done, done, player],
        "acknowledgement is never repeated. OBSERVED QUIRK: a second S3-1 moves phase back to world_received "
        "even though world_acknowledged stays true")
    run("reconnect_starts_clean", None, [player, done, "new_session", done],
        "a new connection builds a fresh State and session logic; nothing is inherited, so S1-11 alone sends nothing")


if __name__ == "__main__":
    wire_cases()
    login_cases()
    decode_cases()
    scenario_cases()
    n = sum(1 for _ in GOLDEN.rglob("*.json"))
    print(f"wrote {n} golden cases under {GOLDEN.relative_to(ROOT)}")
