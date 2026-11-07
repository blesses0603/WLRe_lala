# Offline server dispatcher parity

`ServerProtocol` ports the remaining reachable direct branches of `wlre/network/protocol.py::decode` and `decode_outbound_movement`. It composes the already migrated immutable layout, social, expedition and activity models, plus `LiveDataProtocol`, through typed wrapper records. It has no socket, sends, UI, state application, logging, account storage, or transaction authorization.

Also ported are the small, pure dependencies `npc_dialogue.py::decode_effect` and `services/world/house_navigation.py::decode_floor_extension`. This is only decoding, not the NPC request/continuation workflow or house navigation authority. Short NPC effects remain `event_active` with no inferred details. Position extensions accept only the exact Python lengths and ranges, and never infer a missing house size.

## Behavioral boundaries

- Recognized malformed direct, layout, social, activity, expedition and live-data packets retain their strict exceptions and trailing-byte rules.
- S51-1 partial seven-byte records return only malformed-length metadata, never partial battle attributes.
- Selected event, geometry, gold-limit and expedition-start extensions are discarded as in Python. Unknown packets return only main/sub and payload length.
- S1-4 account/password/save-account echoes are consumed as bytes and never retained in events or diagnostics. Existing world/nearby namecard discard behavior is preserved.
- Attribute values use signed 64-bit storage for negative UInt32 magnitudes. Attack attributes retain their separate unsigned value and sign. Reverse names preserve Python's last-defined alias for duplicate enum values.
- C6-1 outbound movement is direction-specific and strict. Other outbound packets return null without parsing, including credentials.

## Explicit migration gaps

Chat, guild/actions and instance decoders are now integrated with the typed dispatcher. Chat accepts an explicit local role ID via a two-argument overload, while the original one-argument entry point remains supported.

The star-ark, daily-tasks, time-cube, room-storage, recovery, crafting and tent decoders are **not implemented here**. Their known packet keys return `UnsupportedServerDecoderEvent` with the decoder name and payload length. Their body/subtype validity is deliberately not asserted. Unknown keys still return `UnimplementedServerEvent`.

This is significant for S62-1/2/4: Python's crafting decoder shadows older shallow geometry branches, so the dispatcher reports unsupported crafting instead of pretending those packets were decoded. No partial parse or caller-selectable bypass is exposed. These unsupported bodies, including discriminator-dependent unknown subtypes, are not claimed as Python differential parity.

No adapter has been connected to the live state reducer. These decoded events do not grant authority to buy, move, attack, continue dialogue or change accounts.

## Verification

Run from the repository root:

```sh
python dotnet/Lala.Core.Tests/Protocol/generate_server_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release
```

The checked-in generator imports the retained Python implementation directly and produces 312 deterministic, synthetic test packets and exact outcomes at 4,422 truncation boundaries plus a one-byte tail for every packet. It covers every reachable direct packet branch, every release-owned attribute/skill reverse name, nested attack lists, malformed lengths, signed/unsigned extremes, opaque extensions, and representative delegation through each migrated decoder. Existing layout tests additionally verify nonempty world/role/battle/nearby composition.

Tests check discarded secrets/namecards, metadata-only unsupported results, immutable nested snapshots, direction separation, floor verification and fail-closed malformed battle updates. No real captures, credentials, official-server traffic, or network dependency are used.
