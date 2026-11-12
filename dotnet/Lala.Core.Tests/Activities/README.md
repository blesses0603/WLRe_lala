# Activity locks parity

`generate_activity_vectors.py` invokes the original `wlre/core/activity.py` decoder and reducer with 200 deterministic synthetic packets and starting states. It reads no accounts or live captures. Rerun from any directory with Python 3.

Tests also cover all recognized packet variants, truncated/trailing data, hostile role counts, unknown packet/mode behavior, ownership, initial-list replacement, geometry clearing, world-player clearing and detached snapshots.

This is offline typed domain logic, not a network dispatcher or permission to send movement. The caller remains responsible for the session's single-writer ownership. Android and desktop inventory sources have identical activity.py hashes; neither runtime has been connected to this implementation.
