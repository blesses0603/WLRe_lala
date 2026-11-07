# Mixed post-local receive composition

`ServiceStateCoordinator` now runs the four remaining `State.apply` observer
positions after `apply_tent`, in the retained order:

1. `observe_shop_evidence`
2. `observe_efficiency`
3. `apply_actions`
4. `apply_ark`

All eighteen source observer positions have bounded receive implementations.
`ServiceStateSnapshot.IsCompleteState` remains **false**. This is not a full
Python State replacement, a live session, an action scheduler, or authority to
buy, donate, dispatch, fight, answer questions, or activate a catalog.

## Owned state and exact context

The immutable publication owns `ShopEvidence`, `Efficiency`, `GuildActions`, and
`Ark`, in addition to the earlier receive domains. Existing snapshots can be
imported explicitly, including historical pending observations. No receipt can
fabricate an operation or pending request that was never supplied.

- Shop receives the actual updated bag, actual post-local gold, and the same new
  packet count used by the other observers. An unreliable bag/gold observation
  stays unreliable. Neither order descriptors nor settlement claims are created.
- Efficiency receives all returned player knowledge and companions, including
  current stat overrides, after `apply_live` and local dispatch. The projector
  takes the post-local `WorldPlayer`, so identity and name are not stale. Readiness
  flags do not filter known statistics. Missing stats remain unknown, companion
  slot zero stays distinct from the player, and wide labels are not narrowed.
  `NpcNames` is an optional per-observation unverified display mapping, not a
  resource lookup. Reduction uses explicit `ObservedAt` and immutable snapshots,
  never a mutable tracker, a host clock, or fabricated empty knowledge.
- Guild actions receive the already-reduced guild and post-local player/gold.
  Exact receipt acknowledgements can update an imported pending action. Even
  all matching flags and an elapsed deadline cannot complete, spend, timeout,
  reprice, or retry it. The separate `tick` prefix is **not** part of `State.apply`.
- Ark receives the updated daily generation and post-local role. Its own role
  binding and imported pending token/generation remain independent checks.
  These observations neither verify a runtime catalog nor create action authority.

`Observation` retains the exact shop context, efficiency projection, and guild
context. `ArkContext` is present only when the source question-current branch
consumed a runtime read. All contexts and histories are immutable.

## Runtime reads and question persistence boundary

`ServiceObservationInputs.ArkRuntime = null` means no runtime read was supplied.
For a bound pending question or answer receipt that requires a read, omission
throws before publication. This does **not** freeze pending state as though an
unavailable catalog had actually been observed. Supply
`ArkRuntimeObservation.Absent` only for an actual completed unavailable result.
Other event branches do not read runtime and need no runtime input.

`ArkQuestionRuntime` optionally supplies the second read at question text loading.
When omitted, that stage uses the same immutable `ArkRuntime` observation. An
explicit changed second token fails closed. Supplying a token/text map does not
verify its provenance, perform runtime loading, or activate it.

Question memory defaults to `ArkQuestionMemoryAvailability.Deferred`, which says
that no storage adapter ran. Explicit `Unavailable` represents an actually
unavailable boundary and preserves the retained Python caught-failure status.
Both leave the question's actionable known answer empty and preserve historical
`Answers` unchanged. Neither selects, saves, confirms, rejects in storage, solves,
claims a candidate, or sends an answer.

A successful receive can expose one `Observation.ArkMemoryIntent`, bound to the
exact role, token, daily/Ark generations, pending event, question text/options and
selected answer. This is unexecuted output only. Later observations do not carry
it forward implicitly. A future persistence adapter must revalidate identities,
reconcile stored conflicts and quarantine correctly, and report an independently
validated outcome. A server-correct receipt is not proof of a persisted answer.

## Publication and failure contract

The writer and exact-snapshot context checks still precede decoding. Every
successful observation counts once, even when ignored or duplicated. All reducers
stage privately. A missing required runtime observation or a failure in the final
Ark reducer leaves the exact previous snapshot, count, efficiency history and all
other domains intact. This is deliberately stronger than Python's partial mutation
on malformed hand-built events; valid wire behavior and source order are retained.
No implicit role/session invalidation or deduplication is added.

## Retained-Python verification

`ServicePostLocalGenerateVectors.py` runs the **real `State.apply`** and all eighteen
real observers. Transparent wrappers assert their source order and pre/post-local
player, phase and count. Earlier local/service, bag/companion, crafting, party,
instance, tent, knowledge and allocation projections are also compared, rather
than treating them as independent mocks.

The corpus has **26 scenarios, 1,414 checkpoints and 38 event kinds**, including:

- mixed current bag/gold evidence and the 96-entry shop window;
- completed battles, slot-zero companion EXP, wide labels, unknown knowledge,
  repeated/out-of-battle receipts, role changes and clock regression;
- all gold/sell/remaining guild acknowledgement permutations, late binding,
  duplicates, day resets and unchanged pending work at elapsed deadlines;
- Ark imported dispatch/question evidence, role/daily/token changes, separate
  first/second runtime reads, missing texts, and Observe/Confirm/Reject intents;
- all truncated prefixes and trailing bytes of mixed dependent packets;
- repeated rechecks of every previously published composite snapshot.

The real `_remember_question` is traced and then executed with a `QuestionStore`
constructor that raises `OSError` before any storage access. This covers the actual
unavailable boundary without faking persistence success. The intentionally safer
default deferred mode is covered separately in contract tests. The oracle supplies
synthetic runtime/catalog inputs and fixes monotonic time to each explicit recorded
observation; it does not use a host clock, execute commands/ticks, activate candidate
sources, run a solver, or access a real question database.

Source SHA-256 checks normalize only byte pairs CRLF to LF. Fixture parts use the
shared deterministic gzip byte-array helper (`mtime=0`, fixed filename/OS header)
and shared `GzipJson.Decode`; no base64/user-string heap workaround is used. Every
part is below 500 KB. Regeneration must be byte-identical.

```sh
PYTHONPATH=/tmp/daily-assistant-deps python dotnet/Lala.Core.Tests/State/ServicePostLocalGenerateVectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~ServicePostLocal
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release
```

The 12 focused contract cases additionally check post-local context identity,
readiness-independent complete knowledge, default deferred versus actual unavailable
memory, missing runtime rejection, stale-context protection, immutable intents,
last-observer rollback, and absence of tick completion/timeout or fabricated pending.

AccountSession, lifecycle, Android/UI, transport, commands, timers, persistence,
live catalog verification/activation, real platforms and official-server acceptance
remain outside this increment. No Python source or global migration inventory is
changed here.

Verified on this worktree: the focused suite passes **40** cases; full Release Core
passes **19,326** tests; Android lifecycle passes **59**; Desktop Release builds
with zero warnings/errors; and the offline inspector passes **9** checks. Retained
Python discovery runs **2,273** tests, OK with **216** skipped, using the existing
`/tmp/daily-assistant-deps` dependency directory. Regeneration is byte-identical;
the largest generated source file is **439,595 bytes**. These checks do not imply
Android packaging/device, Windows/macOS native execution or live-server acceptance.
