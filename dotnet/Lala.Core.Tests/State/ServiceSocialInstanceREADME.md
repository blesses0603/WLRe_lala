# Mixed party, instance and tent receive composition

`ServiceStateCoordinator` now composes the existing `PartyEventReducer`,
`InstanceReceiveReducer` and `TentReceiveReducer` without adding any action API.
Party runs after the bounded live slices and before expedition; instances run after
expedition. Both use the old local player. Tent runs after local dispatch and uses
the new player and scene. World-player observations reset tent evidence, including
same-role observations, but do not invent party or instance resets.

`ServiceObservationInputs.DeclaredMainCatalogMapIds` is an explicitly supplied,
immutable set of kind=1 instance map IDs. It defaults to empty. These declarations
are not verified catalog provenance, permission to enter, or permission to send.
They are never inferred from `WorldCatalog` or retained for the next observation.
Tent and local world reducers consume the same per-observation world catalog.
Their distinct source rules for classifying private/house scenes remain distinct.

The composite owns read-only `Party`, `Instances` and `Tent` snapshots. Instance
fields retain their deeply immutable `StateValue` representation, including
absent/null/false differences, tuples and imported unknown fields. Every observer
stages privately. Failed decoding, invalid/stale inputs and typed failures before
or after local dispatch publish neither partial state nor a packet count.
This all-or-nothing typed-error behavior is stronger than mutable Python State.

## Differential evidence

`ServiceSocialInstanceGenerateVectors.py` runs the real `State.apply`, not a
replacement reducer chain. Transparent wrappers verify all 18 source observers
run in order and capture their pre/post-local identity, phase and packet count.
Only explicit monotonic time, synthetic stage/catalog rows, stackability and NPC
skill evidence are injected. No receive observer is replaced with a no-op.

The fixture contains 22 mixed scenarios, 679 checkpoints and 50 decoded event kinds. Every checkpoint and
historical snapshot compares all previously covered projections (local session,
world, battle, daily tasks, cube, recovery, guild, activities, storage, expedition,
bag, reservations, companions, crafting and furniture), plus party, ordered teams,
own-team lookup, both instance modes and tent. Shared storage/bag stackability and
companion/local S8 buffers are checked too.

Cases include first/new/same-role world observations, role selection, room creation
and membership, catalog presence/absence/changes, own/other positions, party
requests and late membership, furniture-before-position and position-before-
furniture tent entry, tent errors/return/removal, battle starts/exits/winners,
cooperative reward receipts, malformed packets, clock regression and large counts.
Intended valid sequences are required to decode successfully. Contract tests add
owner-thread checks, imported immutable fields, atomic failures after party and
instance staging and after local dispatch, stale/null contexts, no implicit party
expiry, and no pending-action timeouts or automatic claims.

Regenerate from repository root:

```sh
python dotnet/Lala.Core.Tests/State/ServiceSocialInstanceGenerateVectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release
```

The deterministic gzip fixtures use the shared test-only byte-array helper, not
Base64 string literals. Each generated source file is below 500 KB. Source hashes
normalize CRLF byte pairs only; no text decoding or other normalization occurs.

## Remaining boundaries

This remains offline receive-only Core work. `IsCompleteState` stays false.
The subsequent [knowledge/allocation integration](ServiceKnowledgeAllocationREADME.md)
composes the remaining apply_live receive slices and apply_points_event.
`observe_shop_evidence`, `observe_efficiency`, `apply_actions`
and `apply_ark` remain uncomposed. No party `Expire`, request, tick, timer, reward
settlement, retry, catalog activation, lifecycle, AccountSession, transport, UI or
Android integration is added. Passing these tests does not establish complete
Python migration or live-resource/device/official-server acceptance.

## Verification on this increment

- Core Release: 17,302 tests passed.
- Android lifecycle: 59 tests passed (unchanged implementation).
- Desktop Release: zero warnings/errors; offline self-test passed 9 checks.
- Python discovery: 2,273 tests, OK with 216 skips, using the existing
  `/tmp/daily-assistant-deps` UnityPy dependency directory.
- Two successive fixture regenerations produced identical hashes for all seven
  generated C# files. `git diff --check` passed.

No Android workload/device build, native UI acceptance, login, live send, download,
or official-server test was performed.
