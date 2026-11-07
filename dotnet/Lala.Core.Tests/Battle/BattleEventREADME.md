# Battle event reducer parity

`BattleEventReducer` ports the complete pure reducer in
`wlre/core/state_battle_events.py`. It accepts the existing immutable
`ServerEvent`, `LayoutEvent`, `BattleUnit`, and attack-report types. The one new
local observation, `BattleCommandSentEvent`, represents the fields produced by
`outbound_observations.observed_outbound` for a successful skill/item send, or the
minimal slot observation accepted by the source reducer. It is not a send API,
request, acknowledgement, or authorization.

`BattleEventSnapshot` preserves source defaults and presence through nullable
unobserved scalars and `HasCommands`/`HasLastActions`. Its battle/action counters
use `BigInteger`, and units/commands retain Python insertion order even when a
slot is replaced. A new battle resets all battle-local fields and unit state,
including stale reports, war style, attributes, and exits. Duplicate starts and
attack reports are intentionally not deduplicated. A repeated round keeps
commands; any changed round, including a backwards round, clears them.

Current HP/SP live in `BattleUnitState.Hp` and `.Sp`; `.Layout` retains the
original immutable layout received for that occupant. Only unit replacement or
server S51 replacement attributes alter those current values. S51 is UInt32,
including SP values above the initial layout's UInt16 limit. Values are not
clamped to maxima or interpreted as deltas. Attack actions, targets, flags and
attributes are retained in report order and never applied as damage/healing.
Missing-unit attributes are not buffered. A later unit replaces the entire old
slot occupant, clearing its attribute and exit history.

Own-role identity is a caller-supplied current `uint?`. Unknown identity cannot
match a valid unit/role, while a known role ID of zero is retained. Companion
master ID, account ID, NPC index, slot, and exit extension bytes do not stand in
for role identity. A unit exit marks that occupant; only own-role exit or a
winner ends the battle. Late reports and units do not reactivate it.

## Retained Python evidence

Run from the repository root:

```sh
WLRE_DISABLE_AUTO_CATALOG=1 python dotnet/Lala.Core.Tests/Battle/BattleEventGenerateVectors.py
```

The generator invokes the real `State` defaults, `dispatch_local`, server packet
decoder and local outbound observer. It does not implement a second oracle or
invoke service observers. All inputs are synthetic and offline. The checked-in
vectors record source SHA-256 hashes, **20 sequences and 602 state snapshots**,
including seeded mixed-event traces. Tests compare every battle field, every
unit/layout/equipment/attribute, all original command fields and status, every
nested attack report, plus explicit unit/command key order. They recheck every
past snapshot after subsequent transitions.

The **57 focused tests** additionally cover full UInt32 replacements, input
builder detachment, independent thread branches, unrelated typed events,
strict packet errors, and malformed S51 containment. Partial S51 packets return
the existing `BattleAttributeInvalidEvent`; the reducer ignores the entire
event, including otherwise complete leading records, and accepts subsequent
valid updates. Other malformed packets remain strict decoder errors.

```sh
cd dotnet
DOTNET_CLI_HOME=/tmp/lala-dotnet-home dotnet test Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~BattleEvent
```

## Boundaries

This is a pure battle-domain transition, not the complete Python `State.apply`
observer chain. It does not own `packet_count`, player/account/session lifecycle,
service-added battle fields, command transmission or outbound decoding,
post-battle scheduling, automatic battle, UI, transport, or runtime activation.
The caller records a local command only after a successful send and supplies the
current identity on each applicable event. Arbitrary extra dictionary fields
outside the known typed protocol/local observation schema are not an extension
mechanism. No local resource loading, live server, platform, or device acceptance
is claimed by these offline tests.

Generated sequence JSON is stored as deterministic gzip/base64 text and decoded
only by the test fixture helper. This reduces source size without dropping any
Python checkpoints. Re-run the generator to reproduce the compressed fixture.
