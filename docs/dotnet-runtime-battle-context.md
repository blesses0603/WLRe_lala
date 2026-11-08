# Receive-only runtime battle context

The held connection receive pipeline now preserves the S11-10 battle-style
announcement across the S11-250 battle-start reset. This is a bounded port of
`SessionLogic.receive`, after all supported `State.apply` service observers.
It is not a change to the pure battle reducer: standalone reducers still start
each battle with unknown style until explicitly updated.

A pending announcement is consumed once. Zero is known, while an absent
announcement stays unknown; neither a prior battle's style nor a battle unit's
layout style supplies missing evidence. The first own exit for each current
battle-count/role key clears pending context and marks battle inactive. Duplicate
exits preserve announcements received later. Unit ownership comes from the
received slot's PID, not its master or NPC index. Context does not reset on
winner, event end, role-list or world-player receipts, but every new receive
attempt starts with empty private context.

The full service reduction and overlay stage before one immutable commit.
Observation-input callbacks and public receive snapshots use the same committed
basis. Failed decoding, reduction or pre-commit hooks cannot publish a partial
start. Saved snapshots remain unchanged after later packets or reconnects.

This adds no public API, UI, command sending, scheduler, pending-event handling,
post-battle deadline/status, event-flow changes, resource trust or send authority.
Broader Python receive behavior remains outside this bounded repair.

Verification uses real Python receive traces with synthetic packets, internal
transaction and callback tests, and public two-attempt TCP loopback with synthetic
credentials. No official endpoint, real credentials or device acceptance is used.


## Cooperative fight receipts (overall PR 8.0.32)

Inside the existing first-own-exit gate, style 16 now updates the immutable coop
fight count, consumed-battle marker and last-fight victory after the full service
reduction. A separate consumed-battle guard prevents a second decrement even if
the local role changes. Positive integer counts decrement once; missing, zero,
negative or non-integer counts remain unchanged and victory stays unknown.
Victory requires winner 1/2 and one unambiguous valid column among units with the
nonzero own PID. Exited units remain evidence; Master and NPC identity are not used.
A fresh S186-15 observation resets the source fields, without bypassing the already
used exit gate. Standalone instance observers retain their original behavior.

This is bookkeeping only: no delay is returned, no next-fight action is scheduled,
and no completion/readiness/claim authority follows from the count or victory.
Python's excluded delay arithmetic can fail after the helper returns None on an
already-consumed battle. Six such source failures are explicitly captured by the
oracle; the port compares the bookkeeping and does not reproduce that scheduler.

Validation: 41 real Python receive sequences / 302 snapshots, 86 Python regressions,
1,305 focused and 43,473 full Core tests passed, along with the external consumer,
76 lifecycle, 36 synthetic acceptance and 17 Linux PTY checks. Independent review
found no blockers. Public fragmented TCP fixtures verify duplicates, ambiguity,
rollback and fresh connection generations, not official-server acceptance.
