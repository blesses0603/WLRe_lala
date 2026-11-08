# Bounded received chat in Core publications

`AccountConnectionRuntime.Publication.State.Chat` and the integrated
`AccountRuntime.PublicationSnapshot.Publication.Receive.State.Chat` now retain received chat
before receive-change notifications coalesce. A final unrelated packet cannot erase
prior chat receipts. This is a read-only, in-memory observation API, not a chat sender,
host UI, readiness signal, verified identity, read receipt or delivery confirmation.
`ResourceHeld` and all existing command restrictions are unchanged.

## Retained data and bounds

- `Messages` contains the latest **200** message and system-announcement receipts,
  oldest first, including identical repeated packets. `ReceivedMessageCount` counts
  all receipts and `DroppedMessageCount` makes history eviction explicit.
- Each receipt retains the full decoded event, observation timestamp and local role
  ID at receipt. Item links, quoted text/items, reply-at flag, target, server and reply
  server are retained without flattening. Raw content is not display-cleaned.
- `LatestFeedback` retains only the most recent notice **or** result; `LatestProfile`
  retains only the most recent profile. Neither consumes message history. These are
  latest observations, not an event stream or proof a message was delivered/read.
- The name book retains at most **4096** identities in learn-recency order. Each
  valid learn, even the same name, moves its identity to the newest position.
  Local, unknown cross-server, and every numeric server (including **0**) are
  separate scopes. Text mentions and quoted text never supply identity.
- Names omit characters below U+0020 and U+007F, as in Python. Missing names use
  decimal role IDs. Cached message labels additionally strip bounded markup as in
  Python `plain_text`, while the decoded name and name-book value remain intact.
  A later name refresh makes new copies of historical rows;
  previously published snapshots never change. Cached row names survive name-book
  eviction. Announcement sender labels are `系統`.
- Wire-sized typed-event validation limits text/name/reply fields to **127 UTF-16
  code units**, item and reply-item arrays to **255**, and each item's plugin list
  to exactly **4**. Announcements permit **65529 characters** (uint16 frame body
  minus main/sub and announcement index). Invalid hand-built events fail the whole
  observation, never publish partial chat state or packet count, and are not silently
  truncated. Existing decoder behavior is unchanged, including the non-ASCII system
  announcement encoding-unconfirmed placeholder and identity-missing whisper notice.

The count bounds apply to the current snapshot. A host deliberately retaining older
snapshots retains their private content too and owns its retention policy. Do not
serialize snapshots or content fields into logs. All new types' default `ToString`
output omits text, names and role/server identifiers; explicit content access remains
available to a host that chooses to display it. Cached labels and raw content must
be rendered as literal untrusted text. Raw message/reply content is not rewritten,
links are never opened, and tags are never executed.

## Python relationship and reset semantics

The source contracts are `wlre/ui/chat_ui.py` and
`wlre/services/social/chat_names.py`, not another `State.apply` service observer.
The coordinator composes this projection after local/party/guild reduction and before
its atomic commit. It rescans names on chat, world-player, nearby-player, guild-roster
and guild-profile observations, in player/nearby/guild/event precedence. Unrelated
observations retain the same projection without rescanning.

Two intentional differences are explicit:

1. Existing immutable Core nearby/guild maps do not carry Python insertion order.
   Those groups are learned in ascending role-ID order, so eviction order can differ
   from the Python UI when rescanning more than 4096 identities.
2. Received profile events now learn names and retain the latest profile. Python's
   decoder produces them, but its current UI event filter does not process them.

A newly attached receive attempt starts with empty chat state. Reconnect replacement
and new account generations therefore do not inherit another attempt's names/history.
Role selection, world-player/scene changes and resource observations within the same
attempt do **not** reset history. Old detached publications remain immutable historical
observations, never a way to regain a retired attempt or send authority.

## Verification scope

Synthetic Python NameBook/deque oracle vectors cover scope, sanitization, renaming,
recency/eviction, duplicate receipts and the 200-message bound. Coordinator tests cover
raw payload preservation, immutability, invalid typed payloads and atomic rollback.
A public-API synthetic TCP loopback sends multiple chat frames plus profile/feedback
followed by a heartbeat before the host reads, then verifies a fresh generation starts
empty. A malformed later frame preserves the last committed chat. The no-friend
public consumer also reads the chat publication types. No real accounts, credentials,
official servers, desktop UI or device acceptance are exercised.
