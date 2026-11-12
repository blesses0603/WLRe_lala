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

Ark, daily tasks, time cube, room storage, recovery, crafting and tent receive
families are now integrated. S64-1/16 require an explicit
`CraftingScheduleContext` in the three-argument overload; absent context returns
`UnsupportedServerDecoderEvent` without parsing. Supplying context selects an
already-known schedule layout and does not verify or activate a catalog.
Unknown keys and ignored nonempty S65-2/5/8 extensions still return
`UnimplementedServerEvent`. S65-13 retains the pillar geometry fallback.

Detailed S62 furniture records take precedence over older shallow geometry
branches. Their geometry effect remains subject to the world reducer's house
scope and empty-snapshot guards; decoding alone never authorizes movement.

The offline local coordinator can consume these observations, but no adapter has been connected to a live session. These decoded events do not grant authority to buy, move, attack, continue dialogue or change accounts.

## Verification

Run from the repository root:

```sh
python dotnet/Lala.Core.Tests/Protocol/generate_server_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release
```

The checked-in generator imports the retained Python implementation directly and produces 312 deterministic, synthetic test packets and exact outcomes at 4,422 truncation boundaries plus a one-byte tail for every packet. It covers every reachable direct packet branch, every release-owned attribute/skill reverse name, nested attack lists, malformed lengths, signed/unsigned extremes, opaque extensions, and representative delegation through each migrated decoder. Existing layout tests additionally verify nonempty world/role/battle/nearby composition.

Tests check discarded secrets/namecards, metadata-only unsupported results, immutable nested snapshots, direction separation, floor verification and fail-closed malformed battle updates. No real captures, credentials, official-server traffic, or network dependency are used.
