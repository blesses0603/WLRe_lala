# Offline expedition team parity

Source: `wlre/services/expedition/teams.py` from migration base `01286284`.

Ported: condition evaluation (true/false/unknown), displayed success points and
recommendation awards, exact 1–4-member selection with the original branch bounds
and tie ordering (score, faith deficit, stat cost, team size, slot indices).
NPC metadata remains nullable: missing data never earns a bonus or permits a
joining condition. This is selection only, not expedition start/claim protocol,
catalog loading, inventory consumption, scheduling, UI, or server verification.

`generate_vectors.py` imports the unchanged Python implementation and generates
400 deterministic, synthetic cases covering all condition kinds, missing NPC
metadata, empty pools, recommendation bonuses, faith costs, and ties. Each case
compares condition outcome, success details, and selected slot indices. No live
accounts, captured packets, or credentials are used. Regenerate from repository
root with `python dotnet/Lala.Core.Tests/Expedition/generate_vectors.py`.

Typed inputs use signed 64-bit integer values instead of Python arbitrary
precision. Checked arithmetic fails on overflow rather than silently wrapping.
Negative stats/faith, negative selection bonuses, and duplicate role slot indices are rejected, and optional cancellation throws
instead of returning an incomplete team. These explicit safety checks are not
Python parity claims. Selection rejects negative game values because they invalidate the source's
branch-and-bound assumptions. Suffix top-four bounds are computed in linear
time per condition, with cancellation checks, instead of repeated suffix sorting. The original LRU cache is
not ported; repeated calculations can be cached by a later immutable state layer.

Verification: 400 parity cases and 8 safety/boundary tests; run
`dotnet test dotnet/Lala.Core.Tests --filter FullyQualifiedName~Expedition`.
