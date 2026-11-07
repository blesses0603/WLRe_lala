# Guild-action receive projection

This offline slice ports `wlre/services/social/guild_actions.py` `defaults`,
`valid_member`, `stop_uncertain`, `reset_day`, and `apply_actions`. It consumes the
existing `GuildActionsDecoder` typed events through `ServerProtocol` or the typed
social overload. It adds no commands, requests, reservations, payments, donation
execution, spending, plans, retries, transport, timer, scheduler or session lifecycle.

`GuildActionsReceiveContext` must contain the **post-local** player and gold plus
already-reduced guild roster. Python `State.apply` calls `apply_guild` with the old
player, then `dispatch_local`, then `apply_actions`. A caller must preserve that
order; passing old gold to an exact deduction receipt incorrectly makes it uncertain.
The test harness reproduces this order with the real retained Python and existing
Core local/guild reducers, without changing or integrating the service coordinator.

Source behavior deliberately retained:

- Role list resets all action fields; same-role world observations preserve them;
  changed-role observations reset them. They do not themselves erase the guild roster.
- S39 observations lack identity and are discarded until the actions state is bound
  to the valid roster. Late rosters can bind again; no generation protection is invented.
- Gold and UI sell observations are not subject to the S39 membership guard.
- Pending evidence is imported explicitly, never inferred or created. Typed immutable
  sign/donation pending records retain all source receipt flags, token and deadline.
- Matching gold, remaining and sell acknowledgements alone leave pending intact in
  `apply_actions`. Duplicate gold, inconsistent remaining/counts, identity loss, errors
  and resetting during an action retain the exact uncertainty/clear rules. Uncertainty
  never causes a retry and is not cleared by ordinary successful observations.
- A repeated old sell count after acknowledgement leaves `sell_ack` set, whereas a
  repeated old remaining count after acknowledgement makes the operation uncertain.
- Only explicit S10-5 kind 3 can reset monetary totals. During pending it instead
  preserves epoch/totals and latches uncertainty, while still replacing counts with
  exactly indices 1..100. A later idle reset then clears totals. Sign state 2→1 never
  guesses a new day or resets monetary totals.
- Catalog/readiness/price/donated fields are carried exactly, not refreshed or activated.
  Tokens and imported quote evidence are not verified provenance or permission to act.

## Verification

`generate_guild_action_vectors.py` imports actual retained Python functions with
synthetic packets and explicit pending seeds. It does not invoke `begin`, `command`,
`tick`, runtime catalogs, quote calculation, senders or game services. Its 46 sequences
and 2,370 snapshots cover all sign result bytes, receipt permutations, late and duplicate
traffic, resets, binding changes, zero/max values, unbounded epochs/totals, malformed
packets and seeded mixed sequences. Every historical C# snapshot is rechecked after
all later transitions, including nested pending/quote/count evidence.

The focused C# suite has 67 passing cases. The full base-8a323b1 Release Core suite
passes 17,330 cases; lifecycle passes 59, desktop builds without warnings, and the
offline inspector passes 9 checks. The retained Python guild-action module passes
17 tests, with 2 Tk tests skipped because no display is available. Android package,
Windows/macOS execution, native UI/device and live-server acceptance were not run.

Fixtures use TestSupport deterministic gzip **byte arrays**, not base64 strings.
Source provenance hashes normalize only byte pairs CRLF→LF; BOMs, lone CRs, invalid
UTF-8 and content/whitespace remain significant. Regenerate from repository root:

```
PYTHONPATH=/tmp/daily-assistant-deps python dotnet/Lala.Core.Tests/Social/GuildActions/generate_guild_action_vectors.py
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release --filter FullyQualifiedName~GuildActions
```

## Exact remaining gaps

The non-sending prefix of Python `tick` is **not ported**: pending identity/token/epoch
validation, completion/confirmed totals, explicit-time timeout, and idle catalog
readiness/price/donated display refresh. It must become an explicit observation step
at the scheduler's original source position, never silently run from `State.apply`.
No catalog loader/parser/quote is ported by this slice. `runtime_catalog`,
`common_problem`, `donation_quote`, `begin`, `command`, automatic `tick` planning,
`disconnect`, coordinator publication, account/session lifecycle, and live-server
acceptance remain separate. Ready/Allow/Enabled flags are observations, not authority.
