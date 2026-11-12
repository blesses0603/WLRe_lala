# Normal-attack required-resource integration

`OfflineRuntimeCandidate.OptionalNormalAttackCatalog` exposes immutable normal-attack,
NPC capture and catch-net facts when the existing public `NormalAttackCatalogParser.BuildCatalog`
accepts both required `NpcData_C` and `ItemData_C` payloads. No Lua table, new source,
network request, digest override or invented fallback is involved. Unsupported reviewed
hashes/formats leave this optional property null and `normal_attacks` unavailable.
Required-table decoding still fails on invalid mandatory input before optional parsing.

All skill/daily/instance candidate copies preserve the normal catalog. The resource owner
matches the required table blobs and hashes against SQLite, rechecks the source and publishes
only the resulting candidate. Neither optional database downgrade nor historical snapshots
bypass that gate. Account hold, invalidation, replacement, reconnect and disposal continue
to revoke current resource access through the existing publication lifecycle.

A consumer obtains the catalog through `AccountRuntimePublication.Catalogs` or current
`AccountResourceRuntime.TryReadCatalogs`, then passes `catalog.NormalAttacks` with an
observed `CombatUnitSnapshot` to `CombatRules.NormalSkill`. Absence is unknown, not an
empty trusted catalog. Equipment slot count and actor ownership remain checked by the rule.
This is point-in-time data only: it grants no command, attack or packet permission and does
not activate automatic battle. Consumers must not treat a saved historical catalog as a
current resource grant.

## Evidence and limits

The public external consumer compiles this path without friend access. Runtime tests cover
structural IL verification that required decoding calls the public pinned builder,
unknown hash rejection, ignored supplied trust claims, SQLite NPC/item blob mismatches,
framed/account absence and revocation. Internal synthetic construction tests positive
catalog copying and downstream rule selection; it is not reviewed production acquisition.
Existing parser parity vectors remain synthetic. No reviewed positive NPC/item payload pair
is available in this checkout, so positive production decoding, live server, device and UI
acceptance are not claimed.
