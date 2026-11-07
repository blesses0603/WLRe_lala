# Offline instance decoder parity

`Lala.Core.Instances.InstanceDecoder.Decode(Packet)` ports the complete inbound
`decode_instances` path in `wlre/network/instances.py` at source SHA-256
`af441d0c7e940ff63f49b1459f4d8ad7a29a1927c713210d8a4d2b9b16188295`.

- S85 subtypes: 1, 2, 3, 4, 5, 7, 9, 10, 12, 15, 17, 21.
- S186 subtypes: 2, 3, 6, 10, 11, 13, 15, 17, 20.
- All supported inner kinds are covered, including main objectives/new info,
  cooperative NPC/player match rosters, member snapshots and reward receipts.
- `InstanceEvent` exposes the Python `Type` and `Mode`. Concrete records retain
  variant-specific fields instead of a mutable dictionary or nullable catch-all.
  Arrays, including nested room/member/record/award rows, are immutable snapshots.
- `InstanceLayouts` exposes one-row readers for main/cooperative room listings,
  cooperative member slots, settlement records and awards. Row readers leave the
  following bytes to their caller. Discard a reader after a malformed row throws.

## Source contracts retained

Recognized packets must consume their entire payload. Unknown mains/subtypes
return null. Unsupported S85-5/9/10/21 inner kinds require their discriminator,
then return null without interpreting or validating opaque remaining bytes.
Malformed recognized data throws `ProtocolException`; no partial event escapes.

Count limits match Python: 200 main rooms; 16 main members, score-role IDs and
settlement records; 1–8 cooperative match opponents; 0–8 cooperative member slots;
1000 cooperative rooms; 0–4 nine-byte cooperative awards. There are no inferred
bounds on other source fields, such as listing capacities or phase member counts.

A cooperative snapshot's host is the role ID in wire slot zero, including zero.
It is null only when capacity is zero. Zero-role slots still consume all member
fields, but are omitted from the published member list. Duplicate nonzero IDs
are preserved. Player match rosters retain first-team then second-team order.
NPC match metadata/names are consumed and validated, but are not retained, as in
Python. Main `public`/`defeated` and the 32-bit `kicked` flag compare exactly to 1;
other boolean fields retain the source's nonzero comparison.

An empty S186-10 is a valid empty receipt, not evidence that awards were received.
Result/phase/completion observations do not grant permission to act or imply a
client command was sent successfully.

## Verification

Regenerate the 268 deterministic synthetic Python oracle cases from any cwd:

```sh
python dotnet/Lala.Core.Tests/Instances/generate_instance_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~Instances
```

The 487 instance tests compare complete typed event serialization, null results
and malformed errors against Python; reject every incomplete prefix and one-byte
trailing extension of every recognized fixture; check all unknown subtypes and
inner kinds; exercise exact maximum/zero/over-limit counts, every consumed string
position, UTF-16 errors and padding, unsigned extremes, boolean differences,
slot filtering, roster order and immutable collection ownership. S186-10 correctly
accepts complete nine-byte prefixes, including empty. Reusable row readers are
also checked for boundary consumption and every truncation. Regeneration is
byte-identical. These are synthetic offline fixtures, not live-server captures.

## Excluded work

This slice does not port `list_request` or `member_request`, integrate the common
server dispatcher, mutate session state, send traffic, create/join/enter instances,
start challenges, sweep dungeons or implement Hero actions. It changes no Python
source, UI, Android host or shared inventory/documentation. Source completeness
here applies to the inbound decoder only, not the entire instance feature.
