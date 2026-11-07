"""Generate ownership evidence using the retained Python implementation; offline synthetic state only."""
import json
from dataclasses import fields
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from wlre.core.state import State
from wlre.core.state_ownership import FIELDS


def cs_array(values):
    return "new string[] { " + ", ".join(json.dumps(value) for value in values) + " }"


lines = [
    "// Generated from wlre/core/state.py and state_ownership.py. Synthetic offline evidence only.",
    "namespace Lala.Core.Tests.State;",
    "public static class PythonStateVectors",
    "{",
    "    public static IEnumerable<object[]> Grants()",
    "    {",
]
for owner in FIELDS:
    state = State()
    allowed, denied = [], []
    with state.editing(owner):
        for field in fields(state):
            try:
                state.assert_writer(field.name)
                allowed.append(field.name)
            except RuntimeError:
                denied.append(field.name)
    lines.append("        yield return new object[] { " + json.dumps(owner) + ", " +
                 cs_array(allowed) + ", " + cs_array(denied) + " };")
lines += ["    }"]

state = State(inventory={"items": [{"count": 5}]}, expedition={"status": "idle"},
              auto_battle={"enabled": False}, player={"x": 3})
trace = []

def record(label, action):
    try:
        action()
        trace.append(label + ":ok")
    except RuntimeError as error:
        trace.append(label + ":" + str(error))

with state.editing("expedition"):
    record("inventory", lambda: state.inventory["items"][0].update(count=4))
    record("outer_denied", lambda: state.auto_battle.update(enabled=True))
    try:
        with state.editing("auto_battle"):
            record("inner", lambda: state.auto_battle.update(enabled=True))
            record("inner_denied", lambda: state.expedition.update(status="wrong"))
            raise ValueError("synthetic service failure")
    except ValueError:
        pass
    record("restored_denied", lambda: state.auto_battle.update(enabled=False))
    record("restored", lambda: state.expedition.update(status="done"))
record("unscoped", lambda: state.player.update(x=4))

snapshot = state.snapshot()
worker = threading.Thread(target=lambda: [
    record("thread_write", lambda: state.inventory["items"][0].update(count=0)),
    record("thread_snapshot", state.snapshot),
])
worker.start()
worker.join()
lines += ["    public static string[] NestedTrace { get; } = " + cs_array(trace) + ";"]
projection = {name: snapshot[name] for name in ("inventory", "expedition", "auto_battle", "player")}
lines += ["    public const string NestedSnapshot = " + json.dumps(json.dumps(projection, separators=(",", ":")), ensure_ascii=False) + ";", "}"]
Path(__file__).with_name("PythonStateVectors.cs").write_text("\n".join(lines) + "\n")
