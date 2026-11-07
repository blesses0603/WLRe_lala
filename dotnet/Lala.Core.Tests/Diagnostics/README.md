# Diagnostic boundary parity

`generate_diagnostic_vectors.py` creates offline synthetic expectations by calling
the retained Python command envelope and connection health implementations. It
never reads user accounts, captures, credentials or network state.

- Command validation mirrors Mapping/type checks and Python Unicode code-point
  length. Game-specific command validation remains outside this module.
- Rejection names only expose a bounded ASCII alphanumeric/underscore name with
  at least one alphanumeric character. Arbitrary payload objects are not formatted.
- Connection evidence uses an injected monotonic clock for age and throttling;
  UTC wall time is only the last-receive timestamp. Quiet does not close a session
  or prove logout. Explicit closure forces an event even inside the interval.
- The deterministic Python sequence covers waiting, receive, throttling, silence,
  recovery, wall-clock rollback, long inactivity and explicit closure.

This is the **pure evidence-clock subset** of `connection_health.py`. OS keepalive
configuration, exceptions/errno/code-frame metadata, packet attribution, display
queues and UI monitoring remain unported. Unlike Python's untyped constructor,
this API rejects non-finite/negative timing configuration and non-finite clock
readings. Close reasons are a bounded enum, not arbitrary payload text.
