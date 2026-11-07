# Layout and social decoder parity

Recreate the synthetic vectors from the repository root:

```sh
python dotnet/Lala.Core.Tests/Protocol/generate_layout_vectors.py
```

The generator calls `wlre.network.layouts`, `wlre.network.social_protocol` and
`wlre.network.protocol.decode`. No real captures, private account data, network
requests or Python runtime dependency are introduced into Core.

The 126 valid cases compare every decoded field; 38 malformed cases cover role
indices, battle slots, team sizes/member identities and Unicode, including the
otherwise-discarded private signature. All 17,512 truncation boundaries are
classified by the Python implementation, not assumed invalid. Tests also check
appended bytes, all 16 battle slots, empty and repeated records, 255 equipment
entries, maximum UTF-16 byte length, signed/unsigned numeric extrema, immutable
collections, and absence of private namecard fields from events.

## Consumption contracts

- `ReadRoleList` reads records to the end of the supplied reader. An empty list or
  a prefix ending exactly between complete records is valid, as in Python.
- `ReadWorldPlayer` and `ReadBattleUnit` read one structure and deliberately leave
  any next structure to the caller. They do not call `End()`.
- `LayoutProtocol.Decode` handles S63-1, S3-1, S11-250 and S11-5 as whole packets.
  Declared unit counts and trailing bytes are strictly checked.
- `SocialProtocol.Decode` includes the Python caller's `reader.end()` check.
  S33-2 (team flag) and S23-120 (alchemy space error) intentionally consume opaque
  tails. S13-6 reads complete teams to EOF. Other recognized events reject tails.
- Unknown packet keys or unknown S13-15 leader-transfer kinds return null, without
  exposing their payloads. Missing required bytes still throw `ProtocolException`.
- On a malformed structure, discard the reader and partial work. No decoder
  returns a partially decoded event.

Role maxima use signed 64-bit sums, preserving both totals above UInt32 and
negative signed-star adjustments. Deletion time preserves Python's IEEE 754
binary64 bits rather than assigning new timestamp semantics. Namecard bytes and
signatures are consumed but never retained in the typed events. Nearby-player
events also discard the title, matching their different Python layout.

These are offline Python parity tests only. No dispatcher/state reducer, login,
transport, live commands, resource authorization, automatic battle, platform UI
integration or official-server acceptance is provided by this increment.
