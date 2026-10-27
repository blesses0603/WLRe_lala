"""Reproducible dependency analysis of the legacy ``wlre`` package (stage 0-1).

Run from the repository root:  python3 -I next/tools-python/analyze_deps.py

Static facts come from parsing imports with ``ast`` (function-level imports
count too, so the static graph is conservative). The runtime fact comes from
actually importing the modules in a fresh interpreter and inspecting
``sys.modules``. Nothing here executes game logic or touches the network.
"""
import ast
import collections
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "wlre"
CORE_LAYERS = ("network", "core", "services", "storage")
KEY_MODULES = ["wlre.network.wire", "wlre.network.layouts", "wlre.network.protocol",
               "wlre.network.connection_health", "wlre.network.client", "wlre.core.state",
               "wlre.services.coordination", "wlre.services.items.reservations"]


def module_name(path):
    name = ".".join(path.relative_to(ROOT).with_suffix("").parts)
    return name[:-9] if name.endswith(".__init__") else name


def layer(name):
    parts = name.split(".")
    return parts[1] if len(parts) > 1 else "root"


def imports_of(name, path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = name if path.name == "__init__.py" else name.rsplit(".", 1)[0]
    found, third = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
                third.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[:len(parts) - (node.level - 1)])
                base = base + ("." + node.module if node.module else "")
            else:
                base = node.module or ""
                third.add(base.split(".")[0])
            found.add(base)
            for alias in node.names:
                found.add(base + "." + alias.name)
    return found, third


def build():
    mods = {module_name(p): p for p in PKG.rglob("*.py")}
    graph, third = {}, {}
    for name, path in mods.items():
        found, ext = imports_of(name, path)
        graph[name] = {m for m in found if m in mods and m != name}
        third[name] = ext
    return mods, graph, third


def closure(graph, start):
    seen, stack = set(), [start]
    while stack:
        for nxt in graph[stack.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def sccs(graph, members):
    sub = {m: {x for x in graph[m] if x in members} for m in members}
    index, low, stack, on, out, counter = {}, {}, [], set(), [], [0]
    sys.setrecursionlimit(10000)

    def visit(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in sub[v]:
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            out.append(comp)

    for v in sub:
        if v not in index:
            visit(v)
    return [sorted(c) for c in out if len(c) > 1]


def runtime_probe(modules):
    code = ("import sys\nsys.path.insert(0, %r)\n" % str(ROOT) +
            "".join(f"import {m}\n" for m in modules) +
            "print({k: (k in sys.modules) for k in ('tkinter', 'PIL', 'UnityPy')})")
    return subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=120)


def main():
    mods, graph, third = build()
    core = {m for m in mods if layer(m) in CORE_LAYERS}
    print(f"modules: total={len(mods)}  network/core/services/storage={len(core)}")

    ui_edges = [(a, b) for a in core for b in graph[a] if layer(b) in ("ui", "features")]
    print(f"non-UI -> ui/features imports: {len(ui_edges)}")

    cross = collections.Counter()
    for a in core:
        for b in graph[a]:
            if layer(b) in CORE_LAYERS and layer(a) != layer(b):
                cross[f"{layer(a)}->{layer(b)}"] += 1
    print("cross-layer module edges:", dict(sorted(cross.items())))

    comps = sccs(graph, core)
    print(f"module-level import cycles (strongly connected, size>1): {[len(c) for c in comps]}")
    for comp in comps:
        print("  layers:", dict(collections.Counter(layer(m) for m in comp)))
        for m in comp:
            print("   ", m)

    print("\nstatic transitive closure of key modules (function-level imports included):")
    for m in KEY_MODULES:
        if m not in graph:
            print(f"  {m}: NOT FOUND")
            continue
        reach = closure(graph, m)
        by_layer = dict(collections.Counter(layer(x) for x in reach))
        heavy = sorted(x for x in reach | {m} if third[x] & {"tkinter", "PIL", "UnityPy"})
        print(f"  {m}: {len(reach)} modules {by_layer}")
        for x in heavy:
            print(f"      references {sorted(third[x] & {'tkinter', 'PIL', 'UnityPy'})} in {x}")

    probe = runtime_probe(["wlre.network.protocol", "wlre.core.state", "wlre.network.client"])
    print("\nruntime probe (fresh interpreter imports protocol, state, client):")
    print("  " + (probe.stdout.strip() or probe.stderr.strip()[-300:]))


if __name__ == "__main__":
    main()
