"""Regenerate offline handshake wire vectors. Synthetic credentials only; no sockets."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wlre.network.protocol import login, select_role
from wlre.network.wire import Packet, encode

packets = [
    ("verification", login("synthetic_user", "fake_password", 0, 1, 2)),
    ("formal", login("synthetic_user", "fake_password", 2, 1, 2)),
    ("role1", select_role(1)), ("role2", select_role(2)),
    ("heartbeat", Packet(63, 5)), ("map_ack", Packet(12, 1)),
    ("appear_ack", Packet(3, 2)),
]
path = ROOT / "dotnet/Lala.Core.Tests/Sessions/Handshake/python-vectors.json"
path.write_text(json.dumps([
    {"name": name, "wire": encode(packet, 0xAD).hex().upper()}
    for name, packet in packets
], indent=2) + "\n", encoding="utf-8")
