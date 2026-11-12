# Wire parity tests

The generated `PythonGoldenVectors.cs` contains **synthetic** inputs, never captured
credentials or user traffic. Recreate it from the repository root with:

```sh
python dotnet/Lala.Core.Tests/Protocol/generate_vectors.py
```

The generator calls the retained `wlre.network.protocol` command builders and
`wlre.network.wire.encode` rather than reproducing their algorithms. Golden cases
cover login (dummy strings), role selection, movement, built-in attack, skill,
battle item, field item, empty payload and arbitrary binary payload, each with
XOR keys 0, 173 and 255. Tests compare both body and frame bytes, then replay every
possible two-part split. Additional tests cover coalesced frames, one-byte chunks,
length boundaries, malformed headers, incomplete frames, integer range rejection,
strict UTF-16LE decoding, trailing data and unverified non-ASCII login rejection.

These tests establish **Python implementation parity**, not server protocol
approval or successful game actions. `CandidateCommands` only creates bytes and
has no socket transport. Resource safety, operation authorization, authoritative
session state, live server acceptance and most protocol event layouts are not
implemented by this port. Do not connect these builders directly to a UI button
or transport without those layers.
