# Receive-only inventory service decoders

This slice ports only these receive paths from the retained Python sources:

- `wlre/services/items/room_storage.py`: `decode_storage`, including full `item_save` records via the existing `LiveDataLayouts.ReadItem`.
- `wlre/services/items/recovery.py`: `decode_recovery` and its bottle-kind mapping.
- `wlre/services/items/crafting.py`: `decode_crafting`, `schedule_record`, `furniture_record`, and explicit catalog-layout selection.
- `wlre/services/items/crafting_official_v1286.py`: schedule receive records and recipe-to-item identity lookup only.

There are no requests, sends, network operations, state reducers, reservations, crafting execution, runtime activation, UI, Android or lifecycle changes. Decoding does not authorize an action or establish a verified catalog.

## Integration contract

All decoders return immutable typed `InventoryEvent` observations with `Main`, `Sub` and source-compatible `Type` fields. Unknown keys return null. Event formatting is metadata-only; there is no logging. Collections and identity maps are immutable snapshots. Full storage items reuse the pre-existing immutable `ItemSave` type.

- `StorageDecoder.Decode(Packet)` claims S62-7/11/13/25/57/71/72/73/74/75. S62-25 is claimed only for kind 1, after both header bytes have been read.
- `RecoveryDecoder.Decode(Packet)` claims S23-208.
- `CraftingDecoder.Decode(Packet, CraftingScheduleContext? schedules = null)` claims S64-1/2/3/4/5/6/7/8/10/16/25 and S62-1/2/4/5/76. Furniture events contain detailed room data and geometry flags; they supersede shallow geometry handling of S62-1/2/4.

**S64-1 and S64-16 require an explicit schedule context.** If context is absent, the decoder throws `InvalidOperationException` before examining payload bytes, including empty/malformed payloads. The future dispatcher must return its existing unsupported result for these keys until the caller independently selects a layout from validated runtime provenance. It must not catch that exception and retry as legacy.

Use `CraftingScheduleContext.Legacy` only for an explicitly selected legacy item-ID layout. For independently validated runtime rows, `CraftingScheduleContext.FromRuntimeRows(...)` selects recipe-ID layout if every row has a recipe ID, and legacy layout if rows are empty or all omit it. Mixed keyed/unkeyed rows throw the source `ProtocolException`; invalid/duplicate identity pairs throw `ArgumentException`. Null rows collection is rejected, rather than being interpreted as a missing legacy runtime. The context only carries immutable recipe-to-product identity mappings; it does not verify provenance or activate a runtime. It permits several recipes for one product. Unknown recipe IDs fail instead of becoming product IDs.

Other crafting keys remain context-free and do not consult recipe selection. `FromRuntimeRows` should be invoked only when the selected schedule layout is needed; an invalid hypothetical catalog must not prevent decoding an unrelated furniture/receipt packet.

The Python dispatcher orders these services as storage, expedition, recovery, guild, activity, crafting and tent after its earlier handlers. No dispatcher changes are included here. A non-storage S62-25 result must remain available to later handlers. All modeled fields retain Python meaning; zero indices/counts are accepted where the receive decoder accepts them, even when downstream Python state logic may reject them.

## Error and tail precedence

- Unknown packet keys return null without field reads or tail checks. Known malformed fields throw `ProtocolException`; reader offsets/messages match Python.
- S62-25 reads kind **and** error code before ignoring other house-error kinds. A one-byte unrecognized kind still truncates; a two-byte unrecognized kind ignores arbitrary remaining bytes. Kind 1 rejects tails normally.
- Garage snapshots parse all item records before rejecting duplicate slots. A truncated later record wins over duplicate detection; duplicates win over a final tail error. Nonfinite item times are rejected by the shared layout.
- Material packets reject unknown kind/send-kind before further reads. The count is checked against remaining complete six-byte rows before parsing and before duplicate checks. Only initial batches reject duplicate indices. All recognized material packets require an exact end.
- Recovery validates balance/used bottle kinds before reading their values/targets. Only absolute balance kind 3 rejects negative signed values; deltas and item durability remain signed. Item-update kind 1 deliberately does not validate its bottle byte. Target order and duplicates are retained.
- With a selected crafting layout, runtime identity validation precedes schedule payload parsing. Snapshot length validation precedes row reads. A complete row validates index, identity and count before recipe lookup, so malformed fields precede unknown-recipe failure. Legacy snapshots reject duplicate indices before reading active; recipe snapshots do so after active/end. Active indices are not required to name a returned row. Only swap result 1 reads two indices; other values represent false and reject tails.
- Furniture snapshots read the owner before checking the remaining multiple of 44. Each furniture record consumes its seven reserved bytes without returning them. Duplicate furniture indices, raw kind bytes, zero fields and nonstandard floor/status values are retained. Empty furniture snapshots do not affect geometry; other furniture events do. Parsing never rebuilds geometry.

## Verification

Regenerate from the repository root:

```sh
python dotnet/Lala.Core.Tests/Inventory/generate_inventory_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~InventoryDecoderTests
```

The generator uses deterministic synthetic data only. It executes retained Python receive functions and checks the actual Python dispatcher for recognized events/errors. Synthetic runtime injection exercises the real `active_recipe_catalog` discriminator, not a copied approximation. Every ordinary valid vector retains all fields, exact outcomes at every shorter prefix and an extra-byte tail outcome. Additional cases cover malformed fields, mismatched counts, duplicates, boundary integers, nonfinite item times, unknown keys and layout ambiguity. Compact maximum-count fixtures cover 255 garage items, 65,535 material rows, 255 recovery targets, 255 schedule rows and 1,500 furniture rows without imposing framing limits on the receive decoder. The separate frame codec still owns transport length limits.

The C# contract deliberately requires explicit schedule context where Python may fall back from a missing runtime. Tests verify this safe unsupported boundary separately. None of these tests establishes official-resource acceptance, live-session integration, server acceptance or feature completion.

The common `ServerProtocol` dispatcher preserves these receive events and their
precedence over shallow furniture notifications. S64-1/16 without explicit
`CraftingScheduleContext` return unsupported metadata. Supplying a context
selects the receive layout only; it grants no catalog or action authority.
All 121 valid source vectors are also compared through the common dispatcher.
