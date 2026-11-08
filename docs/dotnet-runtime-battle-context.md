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
post-battle deadline/status, event-flow changes, cooperative fight consumption,
resource trust or send authority. Broader Python receive behavior remains outside
this bounded repair.

Verification uses real Python receive traces with synthetic packets, internal
transaction and callback tests, and public two-attempt TCP loopback with synthetic
credentials. No official endpoint, real credentials or device acceptance is used.
