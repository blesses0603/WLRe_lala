# Battle display rules

`BattleDisplayRules` completes the pure `unit_label` and `attack_lines` functions
from retained `wlre/services/battle/combat.py`. It accepts existing immutable
`BattleEventSnapshot` and received `AttackResultEvent` records, and formats each
reported effect through `CombatRules.EffectText`.

- Labels use the occupant's received name, falling back only for missing, null,
  or empty names. Whitespace, Unicode, punctuation, and slot coordinates survive.
- All 15 normal-attack names and the three defend/flee/capture names override
  received skill names. Unknown skills use their received name or `技能`.
- Action, target, attribute, and duplicate order are preserved. An action without
  targets emits no line. A target without effective attributes emits
  `無有效屬性變化`. Only kind 0 with value 0 is omitted.
- The caller's current snapshot is used even when the battle is inactive, a unit
  exited, or its HP is zero. Attack metadata does not add inferred outcomes.
- Output is immutable and culture-independent. Formatting never changes HP/SP,
  commands, counters, last actions, or any other input. S51 snapshots still own
  absolute HP/SP. No UI, send, transport, observer, or session wiring is included.

The oracle generator calls the actual retained Python functions with synthetic
inputs, checks their non-mutation, records the source SHA-256 (byte CRLF to LF
normalization only), and writes a small human-readable C# JSON fixture. There are
116 cases, 12 direct labels, and 155 attack lines, including seeded mixed reports.
Every case runs under invariant, Arabic, Turkish, and French cultures. Contract
tests cover historical/parallel immutability, authoritative HP, empty reports,
ancillary metadata, and null guards. Tests check physical fixture size in both LF
and CRLF forms, below 500,000 bytes. Wire coordinates, skill IDs, and effect values
retain existing byte/ushort/uint types; arbitrary Python scalar inputs are not
part of the received-event contract.

From the repository root:

```sh
python dotnet/Lala.Core.Tests/Battle/generate_battle_display_vectors.py
python dotnet/Lala.Core.Tests/Battle/generate_battle_display_vectors.py --check
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~BattleDisplay
```

This verifies offline display parity, not live battle acceptance.
