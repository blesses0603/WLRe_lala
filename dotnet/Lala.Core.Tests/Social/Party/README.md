# Receive-only party state

## Ported source and integration boundary

`PartyEventSnapshot` and `PartyEventReducer` port the retained
`wlre/services/battle/party.py` functions `party_defaults`, `apply_party`, `expire`,
`own_team`, and `player_name`. They reuse `Protocol/SocialProtocol.cs` observations
and `PositionSnapshotEvent`, including their existing common server dispatcher.
There are no protocol guesses or new decoder branches.

- `Apply(snapshot, ServerEvent, observedAt, ownRoleId)` accepts decoded server
  observations; the `SocialEvent` overload is equivalent for that domain.
- Supply the **current** player role from before the local world reducer, matching
  `State.apply`'s service-before-local ordering. Role identity and the player's own
  name are not independently stored or inferred by this party snapshot.
- `OwnTeam(ownRoleId)` returns the first team containing that explicit role.
  `PlayerName(roleId, ownRoleId, ownName)` prefers the supplied own name (including
  an empty name), then nearby data, then the invariant decimal role ID. An omitted
  own name uses the same fallback as a missing Python player-name key.
- `observedAt` is an explicitly supplied monotonic seconds value. Only received
  requests consult it, setting a 60-second deadline. Finite values are required
  when creating or expiring requests; no wall clock, timer or scheduler is called.
- `Expire(snapshot, observedAt)` removes requests and outbound evidence at the
  inclusive deadline. The same returned reference means no request expired,
  equivalent to Python's boolean result. `Apply` never implicitly calls expiry.

`Teams` is an immutable ordered array of immutable `TeamSnapshot` records with
unique leader keys after decoded receives. It represents Python's insertion-ordered
mapping, not a sorted roster. `Nearby`, `Requests` and `Outbound` are immutable
maps. All published historical snapshots remain unchanged by later observations.
`Outbound` and `EnabledRequested` only carry caller-supplied evidence so receive
branches can preserve, filter or clear it. This slice never creates outbound
requests, marks an incoming request sent, or sets a requested flag.

## Source semantics preserved

- There is **no party readiness flag in Python**. Defaults have no teams, no
  requests, `Enabled = null`, and status `尚無隊伍資料`. A received empty roster
  updates status without clearing prior teams or establishing readiness.
- Team lists merge by leader; replacing a key retains its position. Duplicate
  leader rows overwrite at that position. Conflicting teams can share a member;
  own-team lookup uses first insertion order rather than guessing which is current.
- Joins create a missing team with its leader, append a missing member only, and
  clear all outbound evidence. The receive reducer does not impose the roster
  decoder's four-member limit or reject zero IDs in incremental events. If the
  updated team contains the explicit own role, remove **all** invites plus every
  request associated with the joined role. Other requests remain.
- Leaving touches every containing team. Leaving as leader or from a team with
  two or fewer members removes the team; other leaves remove that member only.
- Leader transfer pops the old key first and prepends the new leader even if not
  previously a member. A transfer to an existing key replaces that team in place;
  a same-leader transfer moves the team to the end. Missing-old-team transfers
  still clear outbound evidence and all leadership offers and update status.
- Incoming invites/applications/leadership offers only create pending evidence.
  A repeated request resets its status and deadline. Answers do not establish
  membership or remove incoming requests. A zero or missing answer role clears
  all outbound evidence; other roles filter only matching outbound entries.
- Server flag observations set enabled and remove requested-enabled evidence.
  Notices only update status. Rejections update status and clear outbound only.
- Nearby-player data replaces the full known record. Nearby leave never changes
  team membership. Position observations update known other players only; an own
  position filters nearby players to the observed scene without moving their
  coordinates. Ordinary walking does not update nearby party data.
- Role selection, a new world player, initial-data completion and unrelated
  observations do not reset party state. Late joins, rosters or invitations can
  recreate state after removal/expiry. This is source parity, **not stale-event or
  cross-session safety**. The caller still owns lifecycle/generation isolation.

## Deliberately not migrated

`team_command`, `event_text`, packet construction/sending, invitations or responses
initiated by the client, joining/leaving/kicking/leader-transfer actions, automatic
acceptance, party guard, battle automation, transport, `AccountSession`, lifecycle,
service coordinator composition, UI, Android and live-server acceptance remain
outside this slice. No existing Python, shared coordinator, inventory manifest or
GitHub configuration was changed. This snapshot grants no action authority and
must not by itself be used to enable a live command.

## Verification

From the repository root:

```sh
python dotnet/Lala.Core.Tests/Social/Party/generate_party_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~Social.Party
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release
```

The deterministic generator invokes the actual retained decoder, party functions,
State defaults and local dispatcher with synthetic offline data. Other service
observers and command handlers are not executed. One supplied timestamp replaces
the source monotonic call for each observation. Caller pending evidence is seeded
explicitly rather than fabricated by invoking a send path.

The compressed fixture contains **30 sequences / 4,368 snapshots**, including 16
seeded mixed sequences. It covers defaults, merge/order collisions, duplicate and
late events, explicit role changes, nearby replacement/scene filtering, all 256
answer/notice/rejection/flag values, request refresh and exact expiry boundaries,
received roster and incremental size differences, zero/max IDs, Unicode and
ignored private namecard fields. Every shorter prefix and an extra-byte tail for
representative receive packet shapes are compared to Python; accepted prefixes
and ignored tails are retained rather than presumed malformed. Malformed roster
members and a malformed later roster record verify decoding atomicity. Historical
snapshots and helper results are checked after every step. The focused C# suite
contains **66 tests** including explicit contract and source-integrity tests.

Fixture provenance hashes canonicalize only byte pairs `CR LF` to `LF`, in one
pass, preserving bare CR, BOM, invalid UTF-8, NUL and all other bytes. Tests check
all pinned sources under LF/CRLF and reject content edits. The checked-in fixture
is under 500 KB. These offline tests do not establish live membership validity,
session integration, device acceptance or completed feature migration.
