# Ark receive-state boundary

This increment ports the bounded receive-only `defaults()` / `apply_ark()` projection from
`wlre/services/star_ark.py`. It consumes existing typed `ArkEvent` observations and explicit
post-local player, daily-generation and runtime-catalog context. It does not connect a session,
activate a catalog, start an operation or authorize any action.

## Included

- Defaults, role-list reset, same-role preservation and changed-role reset.
- Role gating; starcoin baseline/delta reliability and unbounded revisions; pending dispatch
  payment and ship acknowledgments, mismatch freezes, observed ship/agent changes.
- Snapshot/list replacement, event generations/attempt reset, main additions/completion,
  collect-end/count, skill/new-agent observations, fight results and rejection freezes.
- Question identity/currentness guards, supported award/text guards, question loading, selected
  answer-result correlation, duplicate-result rejection and receipt status.
- Deeply immutable snapshots, including imported pending evidence, opaque unconsumed
  settings/planning fields, nested arrays, old question evidence and historical snapshots.
  Python's unbounded generation/revision/budget arithmetic uses `BigInteger`.
- `ark_collect_reward` remains a no-op here, exactly as in `apply_ark`; no inventory or daily
  task progress is inferred. Both dispatch acknowledgments still do not finish an action.
- Source quirks are retained: freeze does not stop a later recognized observation update;
  duplicate completion can freeze; a detached local pending mutation after freeze cannot
  restore `Pending`; wrong-answer reply index never supplies a guessed correct option;
  `ark_main_added` retains the source event-type provenance separately in `AddedMainEvents`.

## Explicit memory/persistence boundary

Python calls `_remember_question` on question receipt and a correlated answer result. That
helper can create directories/SQLite tables, observe records, resolve reviewed candidates,
record candidate evidence, compute arithmetic, confirm an answer, or quarantine rejection.
Those operations **are not implemented or executed by this reducer**.

`Apply` returns an `ArkReceiveResult` containing the immutable state and, when that source
boundary is reached, one unexecuted `ArkQuestionMemoryIntent`:

- `Observe`: run the complete identity/observation/candidate/solver workflow, not merely a read.
- `Confirm`: a matching correct server receipt must be reconciled with stored conflicting
  evidence before any answer can become confirmed.
- `Reject`: use the selected option, not the answer-result packet's option index; preserve
  the explicit selected-candidate/computed/reviewed-candidate quarantine flag.

Each intent carries exact question ID/text/options/labels, role, runtime token, daily generation,
Ark event generation, pending event, selected index and selected answer. This is evidence,
not a storage transaction, authorization or a promise of persistence. Intent snapshots retain
pre-clear candidate provenance. There is **no completion or replay API** in this increment.
A future adapter must validate the real `ark_questions.identity` / canonical fingerprint rules,
recheck role/version/generations/current pending event and question, perform atomic storage
reconciliation, and return separately validated outcomes. It must not trust an old receipt to
update a newer question. The source's full candidate identity/race checks, observe/candidate/
confirmed/conflict/pending/quarantine outcomes, exact solver, durable claims/attempt tracking,
confirmation/rejection writes and successful `_remember_question` state transitions remain gaps.

The default context is `Deferred`. It clears `KnownAnswer` and answer-kind/source and reports
“題庫處理尚未接入；未讀寫或驗證答案，請人工選答”. It does **not** claim that an uncalled
store failed. The caller can explicitly supply `Unavailable` when that boundary is actually
unavailable; this reproduces the retained Python caught-failure status. Both modes preserve
preexisting `Answers` unchanged, clear the current question's actionable known answer, and
never add/confirm a new answer. Existing `Answers` are carried historical data, not authority.
Question receipt/answer-result status and pending flags still follow the source. Neither mode
retries, sends an answer, clears uncertainty, nor claims successful persistence.

## Composition contract

`State.apply` invokes `apply_daily_tasks` before local dispatch and `apply_ark` **after** local
world/player updates (after tent/shop/efficiency/guild-action observers). Supply that resulting
player role and daily generation, not the pre-world role. Ark's own `Role` is separately checked.

`CurrentRuntime` models the completed `runtime_catalog()` read used by `_question_current`.
`QuestionRuntime`, when supplied, models the second read for question text loading, so a
catalog change between those reads cannot be silently hidden. If omitted it uses the same
immutable observation. `Available` means Python's catalog is not `None`; it does not mean
verified/activated. Tokens are observed tuples, never proof of provenance. Context acquisition
and runtime's own double-token race check are the caller's responsibility.

The domain is not yet attached to `ServiceStateCoordinator`; no shared coordinator,
AccountSession, transport, lifecycle, UI, Android or migration inventory is changed here.
Inputs must be fully decoded typed events and structurally valid imported source pending/state
evidence. `OtherFields` carries unused pending/quote fields but is not interpreted. `Ship = null`
represents Python's absent/empty ship dictionary, distinct from an observed idle ship.

## Differential fixtures and tests

`generate_ark_receive_vectors.py` imports and runs the **retained real** `defaults`, `decode_ark`,
`apply_ark`, `_remember_question`, and identity/fingerprint validation. It injects only synthetic
`runtime_catalog` read results and a `QuestionStore` constructor that raises `OSError` before
any storage access. A trace wrapper records entry to `_remember_question` then invokes the
real function. Intents describe the attempted helper boundary, not SQLite calls that executed.
No fixture uses a reimplementation as its expected-state oracle. No game server, commands,
planner/tick, candidate source activation, filesystem/database storage or accepted-answer
fabrication is involved. Generated fixture files are the only generator output.

There are 371 deterministic sequences, 3,494 state snapshots and 48 memory-boundary intents.
Tests compare every state field and preserve/recheck historical snapshots. Cases include all
receive branches, invalid/truncated/trailing packets, role zero/null/max, large counters,
monetary acknowledgment orders, identity changes, missing texts, second-read version change,
question mismatches, wrong-answer candidate semantics, source caught failures, and mixed runs.
Focused contracts separately test the intentional deferred-mode behavior, immutable intent
identity and no-authority boundaries. Successful persistence/candidate/solver cases are not
represented as covered.

Source SHA-256 hashes use bytes with only CRLF→LF normalization; invalid UTF-8 and bare CR are
not decoded/altered. Fixture parts use the shared `TestSupport/gzip_json_fixture.py` helper
(`mtime=0`, fixed filename/OS header), C# byte arrays and shared `GzipJson.Decode`, avoiding the
assembly's user-string heap. Every source part is under 500 KB.

```sh
PYTHONPATH=/tmp/daily-assistant-deps python dotnet/Lala.Core.Tests/Social/Ark/generate_ark_receive_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~ArkReceive
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release
```

The exact source subset is offline parity, not full Ark service migration or real-server
acceptance. `begin`, `command`, `tick`, planning/fight reward capacity, sending, automatic answer
selection, persistent store operations, live catalog activation and official server acceptance
remain outside this boundary.
