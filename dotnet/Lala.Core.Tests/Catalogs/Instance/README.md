# Offline instance catalog parity

`InstanceCatalogParser` ports the retained `instance_catalog.py` dungeon/cooperative
readers and the joins and validation order in `world/instance_runtime.py:build_catalog`.
It does not read resources, establish same-version provenance, activate a runtime,
generate commands, or send packets. Callers supply the independently verified stage,
text, and item snapshots. `CreationSupported` is only structural compatibility with
the Python schema. `AssetsReady` and `CanSendPackets` remain false.

The raw dungeon row retains all sixteen awards and both sixteen-bit flag lists.
Bound awards preserve their original one-based slots. Stage and cooperative event
fields remain inspectable, including follower rewards that Python does not validate
against items. `DeclaredMainMapIds` contains only unique kind-1 declarations; it does
not establish map readiness. Names are preserved exactly after Python whitespace
validation. No absent name, stage, event, or item is fabricated.

Regenerate from the repository root:

```sh
python dotnet/Lala.Core.Tests/Catalogs/Instance/generate_instance_vectors.py
```

The 859 retained vectors execute the actual decorated Python readers and actual
builder on independent synthetic bytes. No official payloads, network requests,
activation, or digest-pin substitution are used. Nine hash-verified compressed
resources are loaded lazily using bounded scalar theory arguments. Every retained
field, row order, parser diagnostic and exception message is compared, including:

- Zero/maximum/excess counts, exact lengths, and every truncation of representative
  two-row tables and a semantically invalid dungeon.
- All flag bits, seeded unsigned field values, sixteen raw award slots, duplicate
  raw IDs, and validation/trailing-byte ordering.
- Composite identity, required stage/name/item joins, main-map uniqueness,
  optional/required cooperative events, and untouched follower rewards.
- All structural support branches, membership boundaries, Python whitespace and
  unchanged accepted names, including NUL, BOM, and zero-width space.

Separate contracts test owned immutable collections, subspan input, cancellation,
non-authority, and source hashes normalized only for CRLF checkout conversion.
